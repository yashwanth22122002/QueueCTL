#!/usr/bin/env python
# queuectl.py
import click
import json
import os
import signal
import time
import multiprocessing
from datetime import datetime
import db
import worker

# *** MODIFIED PART ***
import tempfile
import psutil  # Import the new dependency
# Use a cross-platform temp directory
PID_DIR = os.path.join(tempfile.gettempdir(), "queuectl_pids")
# *** END MODIFIED PART ***

def ensure_pid_dir():
    """Ensures the directory for storing PIDs exists."""
    os.makedirs(PID_DIR, exist_ok=True)

def get_pid_files():
    """Gets a list of all worker PID files."""
    if not os.path.exists(PID_DIR):
        return []
    return [os.path.join(PID_DIR, f) for f in os.listdir(PID_DIR) if f.endswith('.pid')]

def get_active_workers():
    """Counts how many worker processes are actually running."""
    pids = []
    for pid_file in get_pid_files():
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # *** MODIFIED PART ***
            # Use psutil.pid_exists() for a cross-platform check
            if psutil.pid_exists(pid):
                pids.append(pid)
            else:
                # Process doesn't exist, clean up stale file
                os.remove(pid_file)
            # *** END MODIFIED PART ***

        except (IOError, OSError, ValueError):
            # File is stale or unreadable
            try:
                os.remove(pid_file)
            except OSError:
                pass
    return pids

@click.group()
def cli():
    """
    QueueCTL - A CLI-based background job queue system.
    """
    db.init_db()
    ensure_pid_dir()

# --- Enqueue Command ---
@cli.command()
@click.argument('job_json_string')
def enqueue(job_json_string):
    """
    Add a new job to the queue.
    Example: python queuectl.py enqueue "{\"id\":\"job1\",\"command\":\"echo hello\"}"
    """
    try:
        # Note: Windows cmd.exe requires escaped quotes in the JSON
        job_data = json.loads(job_json_string)
        if 'id' not in job_data or 'command' not in job_data:
            click.echo("Error: Job JSON must contain 'id' and 'command'.", err=True)
            return
        
        db.create_job(job_data)
        click.echo(f"Job {job_data['id']} enqueued.")
    except json.JSONDecodeError:
        click.echo("Error: Invalid JSON string. Remember to escape quotes for cmd.exe.", err=True)
        click.echo('Example: "{\"id\":\"job1\",\"command\":\"echo hello\"}"')
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

# --- Worker Commands ---
@cli.group()
def worker_group():
    """Manage workers."""
    pass

@worker_group.command(name="start")
@click.option('--count', default=1, help='Number of workers to start.')
def worker_start(count):
    """Start one or more workers in the background."""
    processes = []
    
    # This 'if' block is required for 'multiprocessing' on Windows
    if __name__ == '__main__':
        for _ in range(count):
            # 'daemon=True' is problematic on Windows for this model
            # We'll rely on our PID files and stop command
            p = multiprocessing.Process(target=worker.run_worker)
            p.start()
            processes.append(p)
            
            # Store PID in a file
            pid_file = os.path.join(PID_DIR, f"{p.pid}.pid")
            with open(pid_file, 'w') as f:
                f.write(str(p.pid))
                
        click.echo(f"Started {count} worker(s) with PIDs: {[p.pid for p in processes]}")

@worker_group.command(name="stop")
@click.option('--all', is_flag=True, help="Stop all running workers.")
def worker_stop(all):
    """Stop running workers gracefully."""
    pids = get_active_workers()
    if not pids:
        click.echo("No active workers found.")
        return
        
    # *** MODIFIED PART ***
    # Determine the correct signal to send
    stop_signal = signal.SIGBREAK if os.name == 'nt' else signal.SIGTERM
    # *** END MODIFIED PART ***

    for pid in pids:
        try:
            os.kill(pid, stop_signal)
            click.echo(f"Sent stop signal to worker {pid}.")
        except OSError:
            click.echo(f"Worker {pid} already stopped.")
        
        # Clean up pid file
        pid_file = os.path.join(PID_DIR, f"{pid}.pid")
        if os.path.exists(pid_file):
            os.remove(pid_file)

# --- Status & List Commands ---
@cli.command()
@click.option('--state', default=None, help='Filter by state (pending, processing, completed, dead)')
def list(state):
    """List jobs, optionally filtering by state."""
    if state:
        jobs = db.get_jobs_by_state(state)
        click.echo(f"--- Jobs in '{state}' state ---")
    else:
        jobs = db.get_jobs_by_state('pending') + \
               db.get_jobs_by_state('processing') + \
               db.get_jobs_by_state('completed') + \
               db.get_jobs_by_state('dead')
        click.echo("--- All Jobs ---")

    if not jobs:
        click.echo("No jobs found.")
        return

    for job in jobs:
        click.echo(f"ID: {job['id']} | State: {job['state']} | Attempts: {job['attempts']} | Command: {job['command']}")

@cli.command()
def status():
    """Show summary of all job states & active workers."""
    summary = db.get_status_summary()
    active_workers = len(get_active_workers())
    
    click.echo("--- Job Status Summary ---")
    click.echo(f"Pending:    {summary.get('pending', 0)}")
    click.echo(f"Processing: {summary.get('processing', 0)}")
    click.echo(f"Completed:  {summary.get('completed', 0)}")
    click.echo(f"Dead (DLQ): {summary.get('dead', 0)}")
    click.echo("\n--- Worker Status ---")
    click.echo(f"Active Workers: {active_workers}")

# --- DLQ Commands ---
@cli.group()
def dlq():
    """Manage the Dead Letter Queue (DLQ)."""
    pass

@dlq.command(name="list")
def dlq_list():
    """View all jobs in the DLQ."""
    jobs = db.get_jobs_by_state('dead')
    if not jobs:
        click.echo("DLQ is empty.")
        return
        
    click.echo("--- Dead Letter Queue ---")
    for job in jobs:
        click.echo(f"ID: {job['id']} | Attempts: {job['attempts']} | Command: {job['command']}")

@dlq.command(name="retry")
@click.argument('job_id')
def dlq_retry(job_id):
    """Retry a specific job from the DLQ."""
    if db.reset_job_for_retry(job_id):
        click.echo(f"Job {job_id} has been re-queued from DLQ.")
    else:
        click.echo(f"Error: Job {job_id} not found in DLQ.", err=True)

# --- Config Commands ---
@cli.group()
def config():
    """Manage configuration."""
    pass

@config.command(name="set")
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value (e.g., max-retries, backoff_base)."""
    if key not in ('max_retries', 'backoff_base'):
        click.echo(f"Error: Unknown config key '{key}'.", err=True)
        return
    db.set_config_value(key, value)
    click.echo(f"Config '{key}' set to '{value}'.")

@config.command(name="get")
@click.argument('key')
def config_get(key):
    """Get a configuration value."""
    value = db.get_config_value(key)
    if value:
        click.echo(f"{key} = {value}")
    else:
        click.echo(f"Config key '{key}' not found.", err=True)

# Add groups to the main CLI
cli.add_command(worker_group, name="worker")
cli.add_command(dlq)
cli.add_command(config)

if __name__ == '__main__':
    # This __name__ == '__main__' check is
    # CRITICAL for multiprocessing on Windows
    cli() 
