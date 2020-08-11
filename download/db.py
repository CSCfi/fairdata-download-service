"""
    download.db
    ~~~~~~~~~~~

    Database module for Fairdata Download Service.
"""
import sqlite3

import click
from flask import current_app, g
from flask.cli import AppGroup

def get_db():
    """Returns database connection from global scope, or connects to database
    if no conection is already established.

    """
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE_FILE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

        current_app.logger.debug(
            'Connected to database on %s' %
            (current_app.config['DATABASE_FILE'], ))

    return g.db

def close_db(e=None):
    """Removes database connection from global scope and disconnects from
    database.

    """
    db_conn = g.pop('db', None)

    if db_conn is not None:
        db_conn.close()

        current_app.logger.debug(
            'Disconnected from database on %s' %
            (current_app.config['DATABASE_FILE'], ))

def init_db():
    """Initializes database by (re-)creating tables.

    """
    db_conn = get_db()

    with current_app.open_resource('create_tables.sql') as migration_file:
        db_conn.executescript(migration_file.read().decode('utf8'))

    current_app.logger.debug(
        'Initialized new database on %s' %
        (current_app.config['DATABASE_FILE'], ))

def get_download_record(token):
    """Returns a row from download table for a given authentication token.

    :param token: JWT encoded authentication token for which download row is
                  fetched
    """
    db_conn = get_db()
    db_cursor = db_conn.cursor()

    return db_cursor.execute(
        'SELECT * FROM download WHERE token = ?',
        (token,)
    ).fetchone()

def get_task_rows(dataset_id, initiated_after=''):
    """Returns a rows from file_generate table for a dataset.

    :param dataset_id: ID of dataset for which task rows are fetched
    :param initiated_after: timestamp after which fetched tasks may have been
                            initialized
    """
    db_conn = get_db()
    db_cursor = db_conn.cursor()

    return db_cursor.execute(
        'SELECT initiated, date_done, task_id, status, is_partial '
        'FROM generate_task '
        'WHERE dataset_id = ? '
        'AND status is not "FAILURE" '
        'AND initiated > ?',
        (dataset_id, initiated_after)
    ).fetchall()

def create_download_record(token, filename):
    """Creates a new download record for a given package with specified
    authentication token.

    :param token: JWT encoded authentication token used for authorizing file
                  download
    :param filename: Filename of the downloaded package
    """
    db_conn = get_db()
    db_cursor = db_conn.cursor()

    db_cursor.execute(
        'INSERT INTO download (token, filename) VALUES (?, ?)',
        (token, filename)
    )

    db_conn.commit()

    current_app.logger.info(
        "Created a new download record for package '%s' with token '%s'"
        % (filename, token))

def create_task_rows(dataset_id, task_id, is_partial, generate_scope):
    """Creates all the appropriate rows to generate_task and generate_scope
    tables for a given file generation task.

    :param dataset_id: ID of the dataset that the files belong to
    :param task_id: ID of the generation task
    :param is_partial: Boolean value specifying whether the package is partial
                       ie. does not include all of the files in the dataset
    :param generate_scope: List of all the filepaths to be included in the
                           generated package
    """
    db_conn = get_db()
    db_cursor = db_conn.cursor()

    db_cursor.execute(
        "INSERT INTO generate_task (dataset_id, task_id, status, is_partial) "
        "VALUES (?, ?, 'PENDING', ?)",
        (dataset_id, task_id, is_partial))

    for filepath in generate_scope:
        db_cursor.execute(
            "INSERT INTO generate_scope (task_id, filepath)"
            "VALUES (?, ?)",
            (task_id, filepath))

    db_conn.commit()

    current_app.logger.info(
        "Created a new file generation task with id '%s' and scope '%s' "
        "for dataset '%s'"
        % (task_id, generate_scope, dataset_id))

    return db_cursor.execute(
        'SELECT initiated, task_id, status, date_done '
        'FROM generate_task '
        'WHERE task_id = ?',
        (task_id,)
    ).fetchone()

def get_package_row(generated_by):
    """Returns row from package table for a given task.

    :param generated_by: ID of the task that initiated the package generation
    """
    db_conn = get_db()
    db_cursor = db_conn.cursor()

    return db_cursor.execute(
        'SELECT filename, size_bytes, checksum '
        'FROM package '
        'WHERE generated_by = ?',
        (generated_by,)
    ).fetchone()

def get_generate_scope_filepaths(task_id):
    """Returns list of filepaths included in specified task scope.

    :param task_id: ID of the task whose scope is to be fetched
    """
    db_conn = get_db()
    db_cursor = db_conn.cursor()

    scope_rows = db_cursor.execute(
        'SELECT filepath '
        'FROM generate_scope '
        'WHERE task_id = ?',
        (task_id,)
    ).fetchall()

    return set(map(lambda scope_row: scope_row['filepath'], scope_rows))

def get_task_for_package(dataset_id, package):
    """Returns initiated timestamp of a file generation task for a package.

    :param dataset_id: ID of the dataset for which the package is generated
    :param package: Filename of the package whose task initiation is fetched
    """
    db_conn = get_db()
    db_cursor = db_conn.cursor()

    return db_cursor.execute(
        'SELECT '
        '  t.initiated '
        'FROM generate_task t '
        'JOIN package p '
        'ON t.dataset_id = ? '
        'AND p.filename = ? '
        'AND t.task_id = p.generated_by ',
        (dataset_id, package)
    ).fetchone()

db_cli = AppGroup('db', help='Run operations against database.')

@db_cli.command('init')
def init_db_command():
    """Drop any existing tables and create new ones."""
    if (click.confirm('All of the existing records will be deleted. Do you '
                      'want to continue?')):
        init_db()
        click.echo('Initialized the database.')

def init_app(app):
    """Hooks database extension to given Flask application.

    :param app: Flask application to hook the module into
    """
    app.teardown_appcontext(close_db)
    app.cli.add_command(db_cli)
