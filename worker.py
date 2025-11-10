# worker.py
import subprocess
import time
import signal
import sys
import os
import db
from datetime import datetime, timedelta

# Global flag for graceful shutdown
SHUTDOWN_REQUESTED = False

def handle_shutdown_signal(signum, frame):
    """Set the flag to True when a shutdown signal is received."""
    global SHUTDOWN_REQUESTED
    print(f"Worker (PID: {os.getpid()}): Shutdown requested. Finishing current job...")
    SHUTDOWN_REQUESTED = True

def run_worker():
    """The main loop for a single worker process."""
    
    # *** MODIFIED PART ***
    # Register signal handlers for graceful shutdown
    # SIGTERM is for Linux/macOS
    # SIGBREAK is for Windows (sent by 'worker stop')
    if os.name == 'nt':
        signal.signal(signal.SIGBREAK, handle_shutdown_signal)
    else:
        signal.signal(signal.SIGTERM, handle_shutdown_signal)
    
    # Also catch Ctrl+C (SIGINT) in case it's run in the foreground
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    # *** END MODIFIED PART ***
    
    # Initialize DB for this process
    db.init_db()
    
    print(f"Worker (PID: {os.getpid()}) started.")

    while not SHUTDOWN_REQUESTED:
        job = db.fetch_job_atomically()

        if job:
            print(f"Worker (PID: {os.getpid()}): Processing job {job['id']}...")
            execute_job(job)
        else:
            # No job found, sleep to prevent busy-waiting
            if SHUTDOWN_REQUESTED:
                break
            time.sleep(1)
    
    print(f"Worker (PID: {os.getpid()}) shutting down.")

def execute_job(job):
    """Executes the job command and handles success/failure."""
    try:
        # Execute the command
        # On Windows, 'shell=True' is often needed for commands like 'echo'
        result = subprocess.run(
            job['command'],
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,  # 5-minute timeout
        )

        if result.returncode == 0:
            # Success
            print(f"Job {job['id']} completed successfully.")
            db.update_job_state(job['id'], 'completed')
        else:
            # Failure
            print(f"Job {job['id']} failed. stderr: {result.stderr}")
            handle_job_failure(job)

    except subprocess.TimeoutExpired:
        print(f"Job {job['id']} timed out.")
        handle_job_failure(job, timed_out=True)
    except Exception as e:
        # Catch other errors (e.g., command not found)
        print(f"Job {job['id']} execution error: {e}")
        handle_job_failure(job)

def handle_job_failure(job, timed_out=False):
    """Handles failed jobs, retries, and DLQ logic."""
    job_id = job['id']
    new_attempts = job['attempts'] + 1
    
    if new_attempts >= job['max_retries']:
        # Exhausted retries, move to Dead Letter Queue
        print(f"Job {job_id} moved to DLQ after {new_attempts} attempts.")
        
        # --- FIX IS HERE ---
        # We must update BOTH the state and the final attempt count
        now = datetime.utcnow().isoformat()
        with db.get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET state = 'dead', attempts = ?, updated_at = ? WHERE id = ?",
                (new_attempts, now, job_id),
            )
            conn.commit()
        # --- END FIX ---
        
    else:
        # Schedule for retry
        backoff_base = int(db.get_config_value('backoff_base'))
        delay_seconds = backoff_base ** new_attempts
        
        # Add jitter: +/- 10% of the delay
        jitter = delay_seconds * 0.1
        delay_seconds += (jitter * (2 * time.time() % 1 - 1)) # Simple jitter
        
        new_run_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        
        print(f"Job {job_id} failed. Retrying in {delay_seconds:.2f}s (Attempt {new_attempts}).")
        db.update_job_for_retry(job_id, new_attempts, new_run_at)
