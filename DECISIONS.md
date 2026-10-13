## 1. Which indexes did you create and why?

I created indexes on employee codes and joining dates, and attendance indexes on employee code plus date, date plus employee code, and employee code plus punch-in time. These support employee lookups, unique daily attendance, filtered listings, and punch-out queries.

## 2. What happens when two identical punch-ins arrive simultaneously?

The unique compound index on employee code and date allows only one attendance record for that employee on that date. One request succeeds with HTTP 201, while the duplicate request receives HTTP 409.

## 3. What happens when there is a tie at the leaderboard cutoff?

The leaderboard uses MongoDB ranking so employees with equal late-minute totals receive the same rank. All employees whose rank is within the requested limit are returned, including ties at the cutoff.

## 4. How does the department summary count employees with no logs?

The aggregation starts from employees and uses a lookup with preserved empty results. Employees without attendance records therefore remain in the department headcount, while their missing attendance contributes no attendance totals.

## 5. What would you change for 100 times the data?

I would review query execution statistics, optimize indexes based on actual query patterns, and benchmark aggregation pipelines. I would also consider workload monitoring, connection-pool tuning, and database scaling based on measured bottlenecks.