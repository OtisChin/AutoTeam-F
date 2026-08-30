from autotoken.storage import sqlite_store


def test_sqlite_data_version_reader_is_stable_until_an_external_commit(tmp_path):
    db_path = tmp_path / "dashboard-revision.sqlite3"
    sqlite_store.initialize(db_path)
    reader = sqlite_store.SQLiteDataVersionReader(lambda: db_path)
    try:
        initial = reader()
        assert reader() == initial

        with sqlite_store.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO accounts(email, status, account_type, seat_type, data)
                VALUES (?, 'active', 'free', 'unknown', '{}')
                """,
                ("new@example.com",),
            )

        changed = reader()
        assert changed[0] == str(db_path.resolve())
        assert changed[1] > initial[1]
        assert reader() == changed
    finally:
        reader.close()


def test_sqlite_data_version_reader_reopens_when_the_database_path_changes(tmp_path):
    first_path = tmp_path / "first.sqlite3"
    second_path = tmp_path / "second.sqlite3"
    sqlite_store.initialize(first_path)
    sqlite_store.initialize(second_path)
    selected_path = [first_path]
    reader = sqlite_store.SQLiteDataVersionReader(lambda: selected_path[0])
    try:
        first = reader()
        selected_path[0] = second_path
        second = reader()

        assert first[0] == str(first_path.resolve())
        assert second[0] == str(second_path.resolve())
    finally:
        reader.close()
