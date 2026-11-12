from pathlib import Path

import pandas as pd
import pytest

from src import MovieStorage
import main

MOVIE_COLUMNS = ["title", "release_year", "rating", "genre"]
CLEANED_TITLES = [f"Movie {letter}" for letter in "ABCDEFGHIJKLMNOP"]


def test_movies_persist(client, test_storage, uploaded_movies):
    # A second MovieStorage on the same file stands in for a server restart.
    reopened = MovieStorage(test_storage.db_path)
    df = reopened.get()
    original_titles = pd.read_csv(Path("fixtures") / "sample_movies.csv")["title"].tolist()

    assert reopened.count_movies() == 20
    assert len(df) == 20
    assert list(df.columns) == MOVIE_COLUMNS
    assert df["title"].tolist() == original_titles

    stored_ids = [row["id"] for row in reopened.select_columns(["title"], limit=100)]

    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    api_ids = [record["id"] for record in response.json()["data"]]

    assert stored_ids == list(range(1, 21))
    assert api_ids == stored_ids


def test_cache_and_processing(client, uploaded_movies, processing_body):
    # 1. First retrieval for each limit is cached under its own key.
    first_responses = {}
    for limit in (100, 1):
        response = client.get("/movies", params={"limit": limit})
        assert response.status_code == 200
        assert main.cache.get(limit) == response.json()
        first_responses[limit] = response.json()

    assert first_responses[100]["total_rows"] == 20
    assert len(first_responses[100]["data"]) == 20
    assert len(first_responses[1]["data"]) == 1

    # 2. Repeating limit=100 returns the same response.
    repeat = client.get("/movies", params={"limit": 100})
    assert repeat.status_code == 200
    assert repeat.json() == first_responses[100]

    # 3. Processing replaces the data and clears every cached limit.
    process = client.post("/movies/process", json=processing_body)
    assert process.status_code == 200
    report = process.json()
    assert report["validation_rows_removed"] == 0
    assert report["cleaning_report"] == {
        "rows_before": 20,
        "rows_after": 16,
        "rows_removed": 4,
        "columns_before": 4,
        "columns_after": 4,
        "columns_removed": 0,
    }
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    # 4. The next retrieval reads the processed rows and is cached again.
    after = client.get("/movies", params={"limit": 100})
    assert after.status_code == 200
    body = after.json()
    assert body["total_rows"] == 16
    assert [record["title"] for record in body["data"]] == CLEANED_TITLES
    assert [record["id"] for record in body["data"]] == list(range(1, 17))
    assert main.cache.get(100) == body


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    # 1. Populate the cache.
    first = client.get("/movies", params={"limit": 100})
    assert first.status_code == 200
    expected = first.json()

    # 2. Any database read now fails the test.
    def fail_if_called(*args, **kwargs):
        pytest.fail("Database was queried on a cache hit")

    monkeypatch.setattr(main.storage, "select_columns", fail_if_called)
    monkeypatch.setattr(main.storage, "count_movies", fail_if_called)

    # 3. The repeat request must come from the cache.
    second = client.get("/movies", params={"limit": 100})
    assert second.status_code == 200
    assert second.json() == expected


# Part 1 checks, kept from the Part 1 commit.

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_upload_movies(uploaded_movies):
    assert uploaded_movies == {
        "filename": "sample_movies.csv",
        "rows": 20,
        "columns": 4,
        "column_names": MOVIE_COLUMNS,
    }


def test_get_movies_limit(client, uploaded_movies):
    response = client.get("/movies", params={"limit": 2})
    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {"id": 1, "title": "Movie A", "release_year": 2020, "rating": 8.0, "genre": "Drama"},
            {"id": 2, "title": "Movie B", "release_year": 2021, "rating": 8.5, "genre": "Comedy"},
        ],
        "total_rows": 20,
    }


def test_search_movies(client, uploaded_movies):
    default_columns = client.get("/movies/search", params={"min_rating": 8.5, "limit": 2})
    assert default_columns.status_code == 200
    assert default_columns.json() == [
        {"id": 4, "title": "Movie C"},
        {"id": 2, "title": "Movie B"},
    ]

    two_columns = client.get(
        "/movies/search",
        params={"columns": ["title", "rating"], "min_rating": 8.5, "limit": 2},
    )
    assert two_columns.status_code == 200
    assert two_columns.json() == [
        {"id": 4, "title": "Movie C", "rating": 9.0},
        {"id": 2, "title": "Movie B", "rating": 8.5},
    ]


def test_upload_replaces_collection(client, uploaded_movies, sample_csv_bytes):
    response = client.post(
        "/upload",
        files={"file": ("sample_movies.csv", sample_csv_bytes, "text/csv")}
    )
    assert response.status_code == 200
    assert client.get("/movies").json()["total_rows"] == 20
