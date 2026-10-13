# REVIEW.md

## Code Review — Employee Attendance & Analytics API

## 1. Employee Pagination
- Problem: Incorrect pagination can cause records to repeat or be skipped.
- How to notice: Compare consecutive pages of employee results.
- Fix: Calculate the offset using `(page - 1) * page_size`.

## 2. Employee Filtering and Total Count
- Problem: The total count may not match the active filters.
- How to notice: Filter employees by department and compare the returned total.
- Fix: Apply the same filters when counting and retrieving employees.

## 3. Attendance Sorting
- Problem: Sorting only by date can produce inconsistent ordering for records with equal dates.
- How to notice: Request records containing multiple employees on the same date.
- Fix: Use a deterministic sort that includes employee code.

## 4. Attendance Listing Scalability
- Problem: Fetching all records before filtering and pagination wastes memory and time.
- How to notice: Test the endpoint with a large attendance collection.
- Fix: Apply filtering, sorting, and pagination in MongoDB.

## 5. Attendance Response Serialization
- Problem: MongoDB-specific fields or inconsistent timestamp formats may appear in API responses.
- How to notice: Inspect the returned JSON.
- Fix: Return the required response fields and serialize timestamps consistently.

## 6. Concurrent Punch-In Requests
- Problem: Checking for an existing record alone does not prevent concurrent duplicate punch-ins.
- How to notice: Send two punch-in requests for the same employee and date simultaneously.
- Fix: Enforce a unique employee-and-date index and handle duplicate-key errors.

## 7. Unknown Employee Validation
- Problem: Attendance must not be created for an employee who does not exist.
- How to notice: Submit a punch-in request with an unknown employee code.
- Fix: Validate the employee and return the appropriate not-found response.

## 8. Punch-In Timestamp Validation
- Problem: Invalid timestamps or inconsistent timezone handling can produce incorrect attendance dates.
- How to notice: Submit an invalid timestamp or a timestamp with a timezone offset.
- Fix: Validate timestamps and normalize them consistently according to the attendance rules.

## 9. Overnight Shift Handling
- Problem: Calculating lateness using clock times alone can produce incorrect results for overnight shifts.
- How to notice: Test an employee whose shift crosses midnight.
- Fix: Compare the correct shift and attendance datetimes, including the next-day boundary.

## 10. Work-Hours Rounding
- Problem: Ordinary rounding may not follow the required half-up rounding rule.
- How to notice: Test a value exactly halfway between two rounding values.
- Fix: Use the specified half-up rounding rule.

## 11. Overtime Calculation
- Problem: Overtime must respect the required minimum threshold.
- How to notice: Test work time that exceeds the scheduled duration by less than 30 minutes.
- Fix: Apply the specified 30-minute minimum before counting overtime.

## 12. Regularization History Comparison
- Problem: Equivalent timestamps may appear different when comparing timezone-aware and naive datetime values.
- How to notice: Update a record without changing its effective punch times and inspect its history.
- Fix: Normalize punch timestamps before comparing old and new values, and record only actual changes.

## 13. Employee Monthly Analytics
- Problem: Fetching attendance records and calculating statistics in Python does not meet the MongoDB aggregation requirement.
- How to notice: Inspect the implementation and test it with a large attendance collection.
- Fix: Calculate monthly attendance statistics using a MongoDB aggregation pipeline.

## 14. Index-Backed Queries
- Problem: Queries without suitable indexes can become slow as the dataset grows.
- How to notice: Inspect explain output for collection scans.
- Fix: Create appropriate indexes and verify query plans.

## Additional Checks
- The leaderboard rejects a limit greater than 50 with a validation error.
- Explain endpoints were tested for index usage and collection scans.
- A status-only regularization was tested to confirm that unchanged punch times were not recorded as changes.
