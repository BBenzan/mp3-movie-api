import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    HealthResponse,
    MovieCache,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Data Processing API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage()
cache = MovieCache()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return {"status": "ok", "version": app.version}


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Validate a CSV upload and replace the stored movie collection."""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix != ".csv":
        logger.warning(f"Unsupported file format: {suffix or '(none)'}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: '{suffix}'. Only .csv files are accepted.",
        )

    contents = await file.read()

    try:
        df = pd.read_csv(io.BytesIO(contents))
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as error:
        logger.warning(f"Could not read CSV: filename={filename}, error={error}")
        raise HTTPException(
            status_code=400,
            detail=f"Could not read CSV file: {error}",
        ) from error

    column_names = [str(column) for column in df.columns]
    if sorted(column_names) != sorted(MOVIE_COLUMNS):
        logger.warning(f"Unexpected columns: filename={filename}, columns={column_names}")
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have exactly these columns: {MOVIE_COLUMNS}. Found: {column_names}",
        )

    if df.empty:
        logger.warning(f"CSV has no data rows: filename={filename}")
        raise HTTPException(status_code=400, detail="CSV file has no data rows")

    df = df[MOVIE_COLUMNS]
    storage.save(df)
    cache.invalidate()

    logger.info(f"Uploaded movies: filename={filename}, rows={len(df)}")
    return {
        "filename": filename,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
    }


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit movies plus the total stored count, using the cache."""
    cached = cache.get(limit)
    if cached is not None:
        logger.info(f"Returned cached movies: limit={limit}")
        return cached

    data = storage.select_columns(MOVIE_COLUMNS, limit)
    total_rows = storage.count_movies()
    response = {"data": data, "total_rows": total_rows}

    cache.set(limit, response)
    logger.info(f"Retrieved movies: returned_rows={len(data)}")
    return response


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Return id plus the selected fields for movies at or above min_rating."""
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        logger.warning(f"Search failed: columns={columns}, error={error}")
        raise HTTPException(status_code=400, detail=str(error)) from error

    logger.info(
        f"Queried movies: columns={columns}, min_rating={min_rating}, "
        f"returned_rows={len(results)}"
    )
    return results


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and clean the stored movies with MP1 functions, then replace them."""
    df = storage.get()
    if df.empty:
        logger.warning("No movies stored to process")
        raise HTTPException(status_code=400, detail="No movies stored. Upload a CSV first.")

    config_dict = config.model_dump()
    required_columns = config_dict["validation"]["required_columns"]
    numeric_columns = config_dict["validation"]["numeric_columns"]

    missing_numeric = [col for col in numeric_columns if col not in df.columns]
    if missing_numeric:
        logger.warning(f"Numeric columns not found: columns={missing_numeric}")
        raise HTTPException(
            status_code=400,
            detail=f"Numeric column(s) not found in movies: {missing_numeric}",
        )

    try:
        rows_before_validation = len(df)
        validated_df = validate_dataframe(df, required_columns, numeric_columns)
        validation_rows_removed = rows_before_validation - len(validated_df)
        logger.info(f"Validated movies: {rows_before_validation} -> {len(validated_df)} rows")

        df_before = validated_df.copy()
        processed_df = process_data(validated_df, config_dict)
    except ValueError as error:
        logger.warning(f"Processing failed: error={error}")
        raise HTTPException(status_code=400, detail=str(error)) from error

    cleaning_report = create_cleaning_report(df_before, processed_df)
    storage.save(processed_df)
    cache.invalidate()

    logger.info(
        f"Processed movies: validation_removed={validation_rows_removed}, "
        f"rows_before={cleaning_report['rows_before']}, "
        f"rows_after={cleaning_report['rows_after']}"
    )
    return {
        "validation_rows_removed": validation_rows_removed,
        "cleaning_report": cleaning_report,
    }
