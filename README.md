## Employee Attendance & Analytics API

## 1. Project Overview

The Employee Attendance & Analytics API is a backend application developed as part of the HROne Software Engineer hiring assignment.

The application allows an organization to manage employees, record daily attendance, handle punch-in and punch-out operations, correct attendance records, and generate attendance analytics.

The backend is built using Python and FastAPI. MongoDB is used to store employee information and attendance records.

The project also includes database indexes, MongoDB aggregation pipelines, validation, error handling, attendance history, and query execution statistics.

## 2. Technology Stack

## Python

Python is the programming language used to implement the application logic, validation, database operations, and analytics.

## FastAPI

FastAPI is the framework used to create the REST API endpoints. It also provides interactive API documentation through Swagger UI.

## MongoDB

MongoDB stores employee details and attendance records. Aggregation pipelines are used to calculate attendance statistics inside the database.

## PyMongo

PyMongo is the Python library used to connect the application to MongoDB and perform database queries, updates, inserts, and aggregations.

## Pydantic

Pydantic validates incoming request data, including employee details, attendance statuses, and timestamp values.

## Uvicorn

Uvicorn runs the FastAPI application locally.

## python-dotenv

This package loads environment variables from a local `.env` file so database connection details do not need to be hardcoded into the application.

## 3. Development Environment

The project was developed on Windows using Visual Studio Code.

The project folder was created at:

`C:\HROneAttendance\candidate_kit`

The main application file is:

`C:\HROneAttendance\candidate_kit\app\main.py`

The project uses a Python virtual environment named `.venv` to keep its Python dependencies separate from other projects.

Python and Git were installed and checked in the terminal. The Python version available during development was Python 3.14.6, and Git was available as Git 2.55.0.windows.3.

The assignment requires Python 3.11 or newer.

## 4. Project Structure

The main project files are organized as follows:

- `app/main.py` — contains the FastAPI application, request models, validation helpers, database indexes, API endpoints, analytics pipelines, and explain functionality.
- `requirements.txt` — lists the Python packages required by the application.
- `README.md` — explains the project, setup, execution, and testing.
- `REVIEW.md` — documents the starter-code review, verified defects, and corresponding fixes.
- `DECISIONS.md` — explains important technical decisions made during development.
- `.env` — stores local environment variables and must not be committed to Git.
- `.venv/` — contains the local Python virtual environment and must not be committed to Git.

The original candidate kit also contains assignment reference materials and sample data. Only files required for the final submission should be included in the public repository.

## 5. Software Installation and Initial Setup

## Step 1: Install Python

Install Python 3.11 or newer and verify the installation in a terminal:

```powershell
python --version
```

If the command is unavailable, check the Python installation and Windows PATH configuration.

## Step 2: Install Visual Studio Code

Install Visual Studio Code and open the project folder:

`C:\HROneAttendance\candidate_kit`

The built-in terminal is used to run Python commands and start the application.

## Step 3: Install Git

Install Git for Windows and verify it:

```powershell
git --version
```

Git is used to track project changes and publish the final source code to a repository.

## Step 4: Configure MongoDB

The application connects to MongoDB through the `MONGO_URI` environment variable.

MongoDB Atlas was used during development. A local MongoDB installation can also be used if configured correctly.

The database name is configured using `MONGO_DB`. The default database name in the application is `attendance_db`.

The connection URI must remain private and must never be committed to the public repository.

## Step 5: Open the Project Folder

Open the VS Code terminal and navigate to the project directory:

```powershell
cd C:\HROneAttendance\candidate_kit
```

## Step 6: Create a Python Virtual Environment

Create the virtual environment:

```powershell
python -m venv .venv
```

Activate it in Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

After activation, the terminal normally displays `(.venv)` at the beginning of the command prompt.

## Step 7: Install Python Dependencies

Install the packages listed in `requirements.txt`:

```powershell
python -m pip install -r requirements.txt
```

Using `python -m pip` helps ensure that packages are installed into the active Python environment.

## 6. Environment Configuration

Create a local `.env` file in the project root if environment variables are not already configured.

The application supports these variables:

- `MONGO_URI` — MongoDB connection URI.
- `MONGO_DB` — database name; defaults to `attendance_db`.

Example using placeholders:

```dotenv
MONGO_URI=YOUR_MONGODB_CONNECTION_URI
MONGO_DB=attendance_db
```

Replace the placeholder with the actual connection URI in your local environment. Do not put real credentials in this README.

The `.env` file must be excluded from Git. The public repository should contain no database password, API key, or other secret.

## 7. Starting the Application

From the project root, activate the virtual environment and run:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Uvicorn starts the FastAPI application on the local machine.

Open the following URL in a browser:

`http://127.0.0.1:8000/docs`

This opens Swagger UI, where API endpoints can be inspected and tested.

The health endpoint is:

`http://127.0.0.1:8000/health`

A successful health response indicates that the application can communicate with the database.

The application creates the required database indexes during startup. If the database is unavailable or index creation fails, check the terminal output and database configuration.

## 8. Implemented API Functionality

## Employee Management

The application supports creating employees and listing employee records.

Employee listing supports department filtering, pagination, and deterministic sorting. Employee records are checked using unique employee codes.

## Attendance Punch-In

The punch-in endpoint creates an attendance record for an employee and attendance date.

It validates the employee and attendance status, processes the supplied timestamp, calculates the attendance date according to shift rules, and prevents duplicate attendance records through a unique compound index.

## Attendance Punch-Out

The punch-out endpoint finds an eligible attendance record and records the punch-out timestamp.

It checks that the punch-out occurs after punch-in and within the allowed 24-hour interval. Conditional updates prevent two concurrent punch-out requests from both succeeding.

## Attendance Listing

Attendance records can be filtered by employee code, date range, and status.

The endpoint supports pagination and sorting in MongoDB. It also validates date ranges and attendance statuses.

## Attendance Regularization

Managers can correct attendance status or punch timestamps using the regularization endpoint.

The application validates the updated values, recalculates derived attendance fields, and records changes in the attendance history. Conditional updates detect conflicting concurrent changes instead of silently overwriting them.

## Employee Monthly Analytics

The monthly analytics endpoint calculates working days, present days, leave days, late counts, total late minutes, overtime minutes, and attendance percentage.

Attendance statistics are calculated using a MongoDB aggregation pipeline rather than fetching all matching records and calculating the totals in Python.

## Department Summary

The department summary provides department-level headcount and attendance statistics, including presence, lateness, leave, on-duty counts, and average work hours.

The aggregation begins with employees and preserves employees without attendance logs so that department headcount does not exclude them.

## Late Attendance Leaderboard

The leaderboard calculates total late minutes by employee for a selected month. It supports an optional department filter and a configurable limit from 1 to 50.

MongoDB ranking is used so employees tied at the cutoff can retain the same rank and be included according to the ranking rule.

## Department Attendance Trend

The department trend endpoint returns daily attendance statistics over a requested date range.

It uses MongoDB aggregation, date densification, employee lookups, and a seven-row moving average. The date range is limited to 92 days.

## Query Explain Endpoint

The explain endpoint provides MongoDB execution statistics for the supported database operations.

It is intended to help verify index usage and identify collection scans or inefficient query plans.

## 9. Database Indexes

The application creates indexes to support common query patterns.

- Employee code: supports employee lookup and uniqueness.
- Employee joining date: supports filtering employees by joining date.
- Employee code and attendance date: a unique compound index that prevents duplicate attendance for the same employee and date.
- Attendance date and employee code: supports date-oriented attendance queries and sorting.
- Employee code and punch-in timestamp: supports finding relevant attendance records for punch-out.

Index effectiveness should be checked using the explain endpoints against the assignment's larger dataset, not only the small sample.

## 10. Validation and Error Handling

The API uses Pydantic validation and explicit application checks to reject invalid input.

Examples include invalid employee codes, invalid attendance statuses, malformed or out-of-range epoch timestamps, invalid date ranges, punch-out before punch-in, and attendance conflicts.

The application uses appropriate HTTP response codes, including:

- `201` for successful creation.
- `200` for successful retrieval or update.
- `404` when the requested employee or attendance record does not exist.
- `409` for duplicate records or conflicting updates.
- `422` for invalid request data or business-rule violations.
- `503` when the health check cannot reach the database.

## 11. Testing Performed During Development

The API was exercised through Swagger UI at `/docs`.

The following behaviors were tested during development:

- Employee listing and pagination.
- Punch-in and punch-out operations.
- Monthly employee analytics.
- Department summary and department trend.
- Late attendance leaderboard.
- Explain endpoints.
- Regularization history comparison.
- Rejection of a leaderboard limit greater than 50.
- Monthly analytics returning the expected working-day and attendance statistics for test records.

A status-only regularization was also tested to verify that unchanged punch timestamps were not incorrectly recorded as changes in history.

These tests are development checks, not a claim that every assignment requirement has passed. The final submission should also be tested against the required edge cases and a larger dataset.

## 12. Common Development Issues and Lessons

## Python Package Installation

If package imports fail, activate `.venv` and run:

```powershell
python -m pip install -r requirements.txt
```

## PowerShell Command Issues

Use the Windows-appropriate virtual environment activation command. If a command fails, read the exact terminal error before changing project files.

## MongoDB Connection Errors

Check that the MongoDB service or Atlas cluster is available, the URI is correct, and the network and credentials are configured properly.

## Duplicate Index Errors

MongoDB can reject index creation when an existing index has the same key pattern but conflicting options or a different name. Inspect existing indexes and make index definitions consistent instead of repeatedly changing index names.

## API Validation Errors

Use the status code and response message to identify the invalid parameter. For example, the leaderboard rejects a limit greater than 50.

## 13. Running the Application from a Clean Setup

For a fresh checkout:

1. Install Python, Git, and Visual Studio Code.
2. Ensure MongoDB is accessible.
3. Clone the public repository.
4. Open the repository folder in VS Code.
5. Create and activate `.venv`.
6. Install packages from `requirements.txt`.
7. Configure `MONGO_URI` and `MONGO_DB` locally.
8. Start the application with Uvicorn.
9. Open `/docs` and run the health check.
10. Test the required endpoints and edge cases.

Do not run the sample seeding script against a database containing important records without first understanding its behavior. The supplied seed script can delete collections before loading sample data.

## 14. Security and Repository Hygiene

The public repository must not contain:

- `.env` files or database credentials.
- The `.venv` virtual environment.
- Database dumps or private data exports.
- Unnecessary generated files.

Before committing, inspect the Git status and review the files being staged.

The repository must remain public until October 31, 2026, as specified in the assignment instructions. Do not publish the assignment or its solution elsewhere before the restriction ends on November 15, 2026.

## 15. Final Submission Checklist

Before submission, verify that the public repository contains:

- `app/main.py`
- `requirements.txt`
- `README.md`
- `REVIEW.md`
- `DECISIONS.md`

Also verify that:

- The application starts from a clean setup.
- The database connection works.
- Required endpoints return the expected responses.
- Concurrency and validation cases have been tested.
- Analytics are implemented using MongoDB aggregation pipelines.
- Explain output is checked for index usage and collection scans.
- No secrets or virtual environment files are committed.
- The public Git repository URL is submitted through the application form using the same email address used for the application.

## 16. Project Completion

This project demonstrates backend API development, database integration, input validation, concurrency handling, MongoDB aggregation, indexing, and query-plan inspection.

The goal is not only to make the endpoints work with sample records, but also to ensure that the application follows the assignment's business rules and performs correctly with larger datasets.

The final repository should contain the verified implementation, accurate review notes, technical decisions, and reproducible setup instructions.