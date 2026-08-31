import pymysql

# PyMySQL en vez de mysqlclient: mismo backend de Django (django.db.backends.mysql)
# pero sin necesitar compilar contra libmysqlclient-dev en el server.
pymysql.install_as_MySQLdb()
