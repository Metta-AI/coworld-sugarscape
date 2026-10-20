from __future__ import print_function

import mysql.connector
from mysql.connector import errorcode

# import time

# time.sleep(5)

def main():
    """ Python function to create manually the Databased (not used anymore, the db comes in a .sql file) """
    DB_NAME = 'MYSQL_DATABASE'

    TABLES = {}

    TABLES['router'] = (
        "  CREATE TABLE `router` ("
        "  `id` SERIAL PRIMARY KEY,"
        "  `agent_id` INT NOT NULL,"
        "  `data` char(255) NOT NULL,"
        # "  `path` char(255) NOT NULL DEFAULT '',"
        "  `path` TEXT NOT NULL ,"
        "  `asl_file_path` char(255) NOT NULL DEFAULT '',"
        "  `processed` boolean DEFAULT 0 NOT NULL,"
        "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
        "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
        ") ENGINE=InnoDB")

    TABLES['m1'] = (
        "  CREATE TABLE `m1` ("
        "  `id` SERIAL PRIMARY KEY,"
        "  `agent_id` INT NOT NULL,"
        "  `data` char(255) NOT NULL,"
        # "  `path` char(255) NOT NULL DEFAULT '',"
        "  `path` TEXT NOT NULL ,"
        "  `asl_file_path` char(255) NOT NULL DEFAULT '',"
        "  `processed` boolean DEFAULT 0 NOT NULL,"
        "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
        "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
        ") ENGINE=InnoDB")

    TABLES['m2'] = (
        "  CREATE TABLE `m2` ("
        "  `id` SERIAL PRIMARY KEY,"
        "  `agent_id` INT NOT NULL,"
        "  `data` char(255) NOT NULL,"
        # "  `path` char(255) NOT NULL DEFAULT '',"
        "  `path` TEXT NOT NULL ,"
        "  `asl_file_path` char(255) NOT NULL DEFAULT '',"
        "  `processed` boolean DEFAULT 0 NOT NULL,"
        "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
        "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
        ") ENGINE=InnoDB")

    TABLES['m3'] = (
        "  CREATE TABLE `m3` ("
        "  `id` SERIAL PRIMARY KEY,"
        "  `agent_id` INT NOT NULL,"
        "  `data` char(255) NOT NULL,"
        # "  `path` char(255) NOT NULL DEFAULT '',"
        "  `path` TEXT NOT NULL ,"
        "  `asl_file_path` char(255) NOT NULL DEFAULT '',"
        "  `processed` boolean DEFAULT 0 NOT NULL,"
        "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
        "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
        ") ENGINE=InnoDB")

    connected = False

    while (connected == False):
      try:
        cnx = mysql.connector.connect(user='MYSQL_USER', password='MYSQL_PASSWORD',
                                       host='db',
                                       database='MYSQL_DATABASE')
        cursor = cnx.cursor()
        connected = True
      except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
          print("Something is wrong with your user name or password")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
          print("Database does not exist")
        else:
          print(err)

    # def create_database(cursor):
    #     try:
    #         cursor.execute(
    #             "CREATE DATABASE {} DEFAULT CHARACTER SET 'utf8'".format(DB_NAME))
    #     except mysql.connector.Error as err:
    #         print("Failed creating database: {}".format(err))
    #         exit(1)

    try:
        cursor.execute("USE {}".format(DB_NAME))
    except mysql.connector.Error as err:
        print("Database {} does not exists.".format(DB_NAME))
        if err.errno == errorcode.ER_BAD_DB_ERROR:
            create_database(cursor)
            print("Database {} created successfully.".format(DB_NAME))
            cnx.database = DB_NAME
        else:
            print(err)
            exit(1)

    for table_name in TABLES:
        table_description = TABLES[table_name]
        try:
            print("Creating table {}: ".format(table_name), end='')
            cursor.execute(table_description)
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                print("already exists.")
            else:
                print(err.msg)
        else:
            print("OK")

    cursor.close()
    cnx.close()

    # ANTES DE SEPARAR A TUPLA
    # from __future__ import print_function

    # import mysql.connector
    # from mysql.connector import errorcode

    # DB_NAME = 'MYSQL_DATABASE'

    # TABLES = {}

    # TABLES['router'] = (
    #     "  CREATE TABLE `router` ("
    #     "  `id` SERIAL PRIMARY KEY,"
    #     "  `data` char(255) NOT NULL,"
    #     "  `processed` boolean DEFAULT 0 NOT NULL,"
    #     "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
    #     "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
    #     ") ENGINE=InnoDB")

    # TABLES['m1'] = (
    #     "  CREATE TABLE `m1` ("
    #     "  `id` SERIAL PRIMARY KEY,"
    #     "  `data` char(255) NOT NULL,"
    #     "  `processed` boolean DEFAULT 0 NOT NULL,"
    #     "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
    #     "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
    #     ") ENGINE=InnoDB")

    # TABLES['m2'] = (
    #     "  CREATE TABLE `m2` ("
    #     "  `id` SERIAL PRIMARY KEY,"
    #     "  `data` char(255) NOT NULL,"
    #     "  `processed` boolean DEFAULT 0 NOT NULL,"
    #     "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
    #     "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
    #     ") ENGINE=InnoDB")

    # TABLES['m3'] = (
    #     "  CREATE TABLE `m3` ("
    #     "  `id` SERIAL PRIMARY KEY,"
    #     "  `data` char(255) NOT NULL,"
    #     "  `processed` boolean DEFAULT 0 NOT NULL,"
    #     "  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
    #     "  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL"
    #     ") ENGINE=InnoDB")

    # cnx = mysql.connector.connect(user='MYSQL_USER', password='MYSQL_PASSWORD',
    #                                host='db',
    #                                database='MYSQL_DATABASE')
    # cursor = cnx.cursor()

    # def create_database(cursor):
    #     try:
    #         cursor.execute(
    #             "CREATE DATABASE {} DEFAULT CHARACTER SET 'utf8'".format(DB_NAME))
    #     except mysql.connector.Error as err:
    #         print("Failed creating database: {}".format(err))
    #         exit(1)

    # try:
    #     cursor.execute("USE {}".format(DB_NAME))
    # except mysql.connector.Error as err:
    #     print("Database {} does not exists.".format(DB_NAME))
    #     if err.errno == errorcode.ER_BAD_DB_ERROR:
    #         create_database(cursor)
    #         print("Database {} created successfully.".format(DB_NAME))
    #         cnx.database = DB_NAME
    #     else:
    #         print(err)
    #         exit(1)

    # for table_name in TABLES:
    #     table_description = TABLES[table_name]
    #     try:
    #         print("Creating table {}: ".format(table_name), end='')
    #         cursor.execute(table_description)
    #     except mysql.connector.Error as err:
    #         if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
    #             print("already exists.")
    #         else:
    #             print(err.msg)
    #     else:
    #         print("OK")

    # cursor.close()
    # cnx.close()


if __name__ == '__main__':
    main()