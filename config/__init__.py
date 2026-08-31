try:
    import pymysql

    # PyMySQL en vez de mysqlclient: mismo backend de Django
    # (django.db.backends.mysql) pero sin necesitar compilar contra
    # libmysqlclient-dev en el server. Opcional: si no está instalado (ej. un
    # entorno que solo usa SQLite/Postgres), seguimos sin él.
    pymysql.install_as_MySQLdb()
except ImportError:
    pass
