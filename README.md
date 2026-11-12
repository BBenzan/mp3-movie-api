# MP3 Movie API

This project is a FastAPI service that stores one movie collection in SQLite, cleans it with the MP1 data pipeline, and caches repeated retrievals.

Files:
 `main.py` defines the endpoints, and the `src/` package holds the supporting modules:
  - `database.py` opens connections and creates the `movies` table
  - `storage.py` reads and writes that table with SQL
  - `cache.py` wraps a FakeRedis cache
  - `models.py` defines the request and response schemas
  - `middleware.py` logs every request with a request ID. 
  
Endpoints:

  `POST /upload` accepts a CSV with exactly the columns `title`, `release_year`, `rating`, and `genre`, and replaces the stored collection in a single transaction. 
  
  `GET /movies` returns up to `limit` rows ordered by id with the total row count, and `GET /movies/search` filters by minimum rating, sorts, and limits in SQL. `
  
  `POST /movies/process` loads the stored rows, runs validation and cleaning through the `data_pipeline/` modules, and writes the result back to SQLite only if every step succeeds.
  
  `GET /movies` responses are cached for 90 seconds under one key per limit, and every successful upload or processing run clears the cache so clients never receive rows that are no longer stored.
   
The data lives in `data/movies.db`, so it survives a server restart, while the in-memory cache starts empty each time.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux
python -m pip install -r requirements.txt
```

## Start the API

```bash
python -m uvicorn main:app --reload
```

Interactive docs: http://127.0.0.1:8000/docs

## Run the tests

```bash
python -m pytest tests -v
```

## Sample processing request

Upload `fixtures/sample_movies.csv` with `POST /upload`, then send this body to `POST /movies/process`:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

Expected response:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```

Duplicate removal drops the repeated Movie B and Movie D rows (20 to 18), no rows have missing values, and the IQR rule removes the two low-rating outliers, Movie Q (1.0) and Movie R (0.5), leaving 16 rows. A following `GET /movies?limit=100` returns Movie A through Movie P with ids 1 through 16.
