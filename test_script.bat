@echo off
:: This is a Windows Batch file to test queuectl

echo --- [CLEANUP] Removing old database and PIDs ---
del /F /Q queue.db
rmdir /S /Q %TEMP%\queuectl_pids

echo --- [CONFIG] Initializing and setting config ---
python queuectl.py config set max_retries 2
python queuectl.py config set backoff_base 2

echo --- [ENQUEUE] Enqueuing 3 jobs (1 success, 1 fail, 1 invalid) ---
:: This version uses ping/timeout correctly inside the command
python queuectl.py enqueue "{\"id\":\"job-ok\",\"command\":\"echo [OK] This job will succeed ^&^& timeout /t 1 /nobreak ^> NUL\"}"
python queuectl.py enqueue "{\"id\":\"job-fail\",\"command\":\"echo [FAIL] This job will fail ^&^& timeout /t 1 /nobreak ^> NUL ^&^& exit 1\"}"
python queuectl.py enqueue "{\"id\":\"job-invalid\",\"command\":\"not-a-real-command\"}"


echo --- [STATUS] Initial Status (3 pending) ---
python queuectl.py status
python queuectl.py list --state pending

echo --- [WORKER] Starting 2 workers in background ---
python queuectl.py worker start --count 2

echo --- [WAIT] Waiting 10s for jobs to process, fail, and retry... ---
:: FIX: Use 'ping' as a reliable sleep instead of 'timeout'
:: Pinging 11 times gives 10 one-second intervals.
ping 127.0.0.1 -n 11 > nul

echo --- [WORKER] Stopping workers ---
python queuectl.py worker stop

echo --- [STATUS] Final Status (1 completed, 2 dead) ---
python queuectl.py status

echo --- [VERIFY] Verifying Completed ---
python queuectl.py list --state completed

echo --- [VERIFY] Verifying DLQ ---
python queuectl.py dlq list

echo --- [RETRY] Retrying 'job-fail' from DLQ ---
python queuectl.py dlq retry job-fail

echo --- [STATUS] Status after DLQ retry (1 pending, 1 dead) ---
python queuectl.py status

echo --- [WORKER] Starting 1 worker for the retried job ---
python queuectl.py worker start --count 1

echo --- [WAIT] Waiting 5s for the failed job to fail again... ---
:: FIX: Use 'ping' (6 pings for 5 intervals)
ping 127.0.0.1 -n 6 > nul

echo --- [WORKER] Stopping worker ---
python queuectl.py worker stop

echo --- [STATUS] Final-Final Status (1 completed, 2 dead) ---
python queuectl.py status
python queuectl.py dlq list

echo --- [TEST] Test script complete ---