# Architecture & Design (`architecture.md`)

This document provides a brief overview of the design principles and core components of `queuectl`.

## 1. High-Level Design

The system is a **decoupled, producer-consumer** application built on three main pillars:
1.  **The CLI (`queuectl.py`):** The "Producer." It's the user's entry point for enqueuing jobs and managing the system.
2.  **The Database (`db.py`):** The "Source of Truth." A central SQLite database that acts as the persistent job queue and state manager.
3.  **The Workers (`worker.py`):** The "Consumers." A pool of background processes that pull jobs from the database, execute them, and update their status.

## 2. Core Components

### `queuectl.py` (The CLI)
* **Technology:** `click`
* **Responsibilities:**
    * Provides a clean, user-friendly command-line interface.
    * Parses user input (e.g., job JSON, config settings).
    * Calls the appropriate functions in `db.py` to enact changes (like enqueuing a job or setting config).
    * Manages the worker lifecycle using `multiprocessing.Process` to start them and `os.kill` with `psutil` to stop them.

### `db.py` (The Database Layer)
* **Technology:** `sqlite3` (in WAL mode)
* **Responsibilities:**
    * Manages all database schema (`CREATE TABLE ...`).
    * Handles all `INSERT`, `UPDATE`, and `SELECT` queries.
    * **Crucially, it implements the concurrency lock.** All other parts of the system are "dumb" and just call functions from this file. This centralizes the persistence logic.

### `worker.py` (The Worker Logic)
* **Technology:** `multiprocessing`, `subprocess`, `signal`
* **Responsibilities:**
    * Runs in a continuous loop, polling the database for jobs.
    * Executes job commands using `subprocess.run()`.
    * Handles job success, failure, and retries (including calculating exponential backoff).
    * Catches `SIGBREAK` (Windows) / `SIGTERM` signals to perform a graceful shutdown (finishing its current job before exiting).

## 3. Job Lifecycle Flow

1.  A user runs `queuectl enqueue`. The CLI (`queuectl.py`) calls `db.create_job()`, which inserts a job with `state = 'pending'`.
2.  A `worker.py` process, in its loop, calls `db.fetch_job_atomically()`.
3.  `db.py` executes the **atomic lock** (see below). It finds the job, updates its `state = 'processing'`, and returns it to the worker.
4.  The worker executes the job's `command`.
    * **On Success (exit 0):** The worker calls `db.update_job_state(id, 'completed')`.
    * **On Failure (exit != 0):** The worker calls `handle_job_failure()`.
        * If `attempts < max_retries`, it calls `db.update_job_for_retry()`, which sets `state = 'pending'`, increments `attempts`, and sets a future `run_at` timestamp.
        * If `attempts >= max_retries`, it calls `db.update_job_state(id, 'dead')`.

## 4. Critical Design: Concurrency & Locking

**The most important design decision in this project is how to prevent race conditions.**

* **Problem:** If two workers query for a `pending` job at the same *exact* millisecond, they might both grab the same job, leading to duplicate execution.
* **Solution:** We use the **database itself as the lock**. We do *not* use Python-level locks (`threading.Lock`), as they do not work across different processes.
* **Implementation:** The `fetch_job_atomically()` function in `db.py` uses `BEGIN IMMEDIATE TRANSACTION`.
    1.  `BEGIN IMMEDIATE` acquires an **exclusive write lock** on the database *immediately*.
    2.  No other worker can even *start* its own `BEGIN IMMEDIATE` transaction until the first one is finished.
    3.  Inside this locked transaction, we `SELECT` the first pending job AND `UPDATE` its state to `processing`.
    4.  We `COMMIT`, which releases the lock.

This entire "find-and-lock" operation is atomic. It guarantees that a pending job can only ever be picked up by **one worker**.