#!/usr/bin/python
#-*- coding: latin-1 -*-

#https://dev.mysql.com/doc/connector-python/en/connector-python-example-connecting.html

import mysql.connector
from mysql.connector import errorcode

import random

import time

def request_to_register(model, qtd):
  """ Python code that requests the register to insert a certain amount of new agents in the simulation """

  cnx = mysql.connector.connect(user='MYSQL_USER', password='MYSQL_PASSWORD',
                                 host='db',
                                 database='MYSQL_DATABASE')
  retorno = False
  for agent_id in range(1, qtd):
    cursor = cnx.cursor()
    # add_agent = ("INSERT INTO router "
    #              "(agent_id, data) "
    #              "VALUES (%s, %s)")
    # data = [random.randint(5, 25), random.randint(1, 4) random.randint(1, 6)]
    data = []
    data.append(random.randint(5, 25))
    data.append(random.randint(1, 4))
    data.append(random.randint(1, 6))

    # data_agent = (agent_id, data)
    sql1 = "INSERT INTO "+model+ " (agent_id, data) "+"VALUES ('"+agent_id+"', '"+data+"');"

    # # Insert new employee
    # cursor.execute(add_employee, data_employee)
    try:
        # cursor.execute(add_agent, data_agent)
        cursor.execute(sql1)
        # Make sure data is committed to the database
        cnx.commit()
        retorno = True
    except mysql.connector.Error as err:
        print("Failed insertind on database: {}".format(err))
        retorno = False
    finally:
        cursor.close()

    if (retorno == False):
        break

  cnx.close()
  return retorno


if __name__ == '__main__':
    main()