\# QueueCTL - Backend Job Queue System



`queuectl` is a CLI-based background job queue system built in Python. It manages background jobs with worker processes, handles retries using exponential backoff, and maintains a Dead Letter Queue (DLQ) for permanently failed jobs.



This project uses \*\*Python\*\* with `click` for the CLI, `sqlite3` for persistent storage, and `multiprocessing` for concurrent workers. It is designed to be robust and concurrency-safe.



---
## 📺 Demo Video

A full walkthrough demo of the system can be viewed here:

👉 **https://drive.google.com/file/d/1ffPaceGlrKKGc9h-HMLjO3QXbT8hi1PL/view?usp=sharing**



\## 🚀 Setup Instructions (Windows)



1\. \*\*Clone the Repository\*\*

&nbsp;   ```bash

&nbsp;   git clone https://github.com/yashwanth22122002/QueueCTL.git

&nbsp;   cd queuectl

&nbsp;   ```



2\. \*\*Create and Activate Virtual Environment\*\*

&nbsp;   ```bash

&nbsp;   python -m venv venv

&nbsp;   venv\\Scripts\\activate

&nbsp;   ```



3\. \*\*Install Dependencies\*\*



&nbsp;   This project requires:

&nbsp;   - `click`

&nbsp;   - `psutil`



&nbsp;   Install all dependencies:

&nbsp;   ```bash

&nbsp;   pip install -r requirements.txt

&nbsp;   ```



4\. \*\*Initialize the Database\*\*



&nbsp;   The database (`queue.db`) and its tables are created automatically the first time you run any `queuectl` command.



&nbsp;   Run:

&nbsp;   ```bash

&nbsp;   python queuectl.py status

&nbsp;   ```



---



\## 💻 Usage Examples



All commands are executed via:



```

python queuectl.py <command>

```



---



\### ✅ 1. Configure the System



```bash

python queuectl.py config set max\_retries 3

python queuectl.py config set backoff\_base 2

```



---



\### ✅ 2. Enqueue Jobs



⚠ \*\*Windows Command Escaping:\*\*  

`"` → `\\"`  

`\&` → `^\&`  

`>` → `^>`



```bash

\# Enqueue a job that will succeed

python queuectl.py enqueue "{\\"id\\":\\"job-1\\",\\"command\\":\\"echo Job 1 is done ^\&^\& timeout /t 1 /nobreak ^> NUL\\"}"



\# Enqueue a job that will fail

python queuectl.py enqueue "{\\"id\\":\\"job-fail\\",\\"command\\":\\"echo Job failed ^\&^\& exit 1\\"}"

```



---



\### ✅ 3. Check Queue Status



```bash

python queuectl.py status

```



Example Output:



```

--- Job Status Summary ---

Pending:    2

Processing: 0

Completed:  0

Dead (DLQ): 0



--- Worker Status ---

Active Workers: 0

```



---



\### ✅ 4. Start \& Stop Workers



Start two workers:



```bash

python queuectl.py worker start --count 2

```



Stop workers:



```bash

python queuectl.py worker stop

```



---



\### ✅ 5. List Jobs by State



```bash

python queuectl.py list --state pending

```



---



\### ✅ 6. Manage the Dead Letter Queue (DLQ)



```bash

python queuectl.py dlq list

python queuectl.py dlq retry job-fail

```



---



\## 🏛️ Architecture Overview



\### ✅ Job Lifecycle



```

pending → processing

&nbsp;  └→ completed

&nbsp;  └→ failed → retry → retry → dead (DLQ)

```



\### ✅ Data Persistence



\- Uses a \*\*single SQLite file\*\*: `queue.db`

\- WAL mode enables concurrent reads/writes

\- Crash-safe; workers can restart safely



\### ✅ Worker Logic



Each worker:



1\. Atomically locks the next pending job  

2\. Marks it as `processing`  

3\. Executes the command  

4\. Captures stdout \& stderr  

5\. Applies retry policy:  

&nbsp;  ```

&nbsp;  backoff = backoff\_base \*\* attempts

&nbsp;  run\_at = now + backoff

&nbsp;  ```

6\. Moves job to DLQ after max retries  

7\. Sleeps 1s when idle  

8\. Handles graceful shutdown on `SIGBREAK`



PID files tracked under:



```

%TEMP%\\queuectl\_pids

```



---



\## 🧠 Assumptions \& Trade-offs



\### ✅ SQLite vs SQL Server / PostgreSQL



\- ✅ Zero setup  

\- ✅ Robust enough for concurrency  
 



\### ✅ PID Files for Worker Management



\- ✅ Cross-platform \& simple  





\### ✅ Shell-Based Command Execution



\- ✅ Supports complex shell pipelines  

 



---



\## 🧪 Testing Instructions



\### ✅ Automated Test Script



Run:



```bash

test\_script.bat

```



This script:



1\. Cleans DB + PID files  

2\. Sets config  

3\. Enqueues:

&nbsp;  - ✅ success job  

&nbsp;  - ❌ failure job  

&nbsp;  - ❌ invalid command  

4\. Starts 2 workers  

5\. Waits for job processing  

6\. Moves failed jobs to DLQ  

7\. Stops workers  

8\. Retries DLQ job  

9\. Starts worker to process retry  

10\. Moves job back to DLQ after failure  



Expected Output Snippet:



```

--- \[CLEANUP] Removing old database and PIDs ---

--- \[ENQUEUE] Enqueuing 3 jobs ---

--- \[WORKER] Starting workers ---

job-ok completed

job-fail moved to DLQ

job-invalid moved to DLQ

--- \[STATUS] Final Status ---

```



---



\### ✅ Manual Verification



1\. Enqueue:

&nbsp;  ```bash

&nbsp;  python queuectl.py enqueue "{\\"id\\":\\"job-persist\\",\\"command\\":\\"echo persistence test\\"}"

&nbsp;  ```



2\. Verify:

&nbsp;  ```bash

&nbsp;  python queuectl.py status

&nbsp;  ```



3\. Close terminal, reopen, run:

&nbsp;  ```bash

&nbsp;  python queuectl.py status

&nbsp;  ```



✅ The job persists.



---





