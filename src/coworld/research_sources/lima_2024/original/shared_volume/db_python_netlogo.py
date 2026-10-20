#!/usr/bin/python
#-*- coding: latin-1 -*-

#https://dev.mysql.com/doc/connector-python/en/connector-python-example-connecting.html

import mysql.connector
from mysql.connector import errorcode

import random

import time

import requests

import os

def host_port():
  """ Internal function, to inform host and port to access the API """
  host = os.environ['host']
  #host = "api"
  #host = "144.22.197.41"
  port = "5000"
  return host, port

if __name__ == '__main__':
  print("")


def testing_exception(error):
  """ Function create for testing only, testing the creation of a custom exception """
  raise Exception(error)

def request_to_register(model, min, max):
  """ Function that requests to register to create a certain amount of agents. Asked by NetLogo. Calls the register_agents_on_platform endpoint on API """
  start = time.time()
  host, port = host_port()
  print("Start time request_to_register: "+str(start))
  print("Host: "+host)
  # start = time.time()
  # print("hello")
  # end = time.time()
  # print(end - start)
  retorno = False
  while retorno == False:
    try:
      # response = requests.post('http://localhost:5000/api/v1/resources/request_to_register', json = {"model":model, "min":min, "max":max}, timeout=5)
      # response = requests.post('http://api:5000/api/v1/resources/request_to_register', json = {"model":model, "min":min, "max":max}, timeout=120)
      

      # response = requests.post('http://api:5000/api/v1/resources/request_to_register', json = {"model":model, "min":min, "max":max})
      
      #response = requests.post('http://api:5000/api/v1/resources/register_agents_on_platform', json = {"model":model, "min":min, "max":max})
      response = requests.post('http://'+host+':'+port+'/api/v1/resources/register_agents_on_platform', json = {"model":model, "min":min, "max":max}, timeout=120)
      print("Response from API: "+response.text)
      response.raise_for_status()

      #print(response)
      print("Function worked well")
      retorno = True
    except requests.exceptions.HTTPError as errh:
        print(errh)
        print("Error type 1, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
        print("Error type 2, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.Timeout as errt:
        print(errt)
        print("Error type 3, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.RequestException as err:
        print(err)
        print("Error type 4, sleeping and retrying")
        time.sleep(1)

  print("Left loop")
  end = time.time()
  print("End time request_to_register: "+str(end - start))
  return retorno

def send_agent_to_alive(agent_id, model):
  """ Function used by NetLogo, when the simulation is over. It removes an agent from the simulation and sends it to the API (to be inserted in alive_agents table). Calls the model_to_alive endpoint on API """
  start = time.time()
  host, port = host_port()
  print("Start time send_agent_to_alive: "+str(start))
  retorno = False
  while retorno == False:
    try:
      # response = requests.post('http://localhost:5000/api/v1/resources/model_to_router', json = {"agent_id":agent_id, "data":data, "path":path}, timeout=5)
      #response = requests.post('http://api:5000/api/v1/resources/model_to_router', json = {"agent_id":agent_id, "data":data, "path":path}, timeout=5)
      
      #response = requests.post('http://api:5000/api/v1/resources/model_to_alive', json = {"agent_id":agent_id, "model":model})
      response = requests.post('http://'+host+':'+port+'/api/v1/resources/model_to_alive', json = {"agent_id":agent_id, "model":model}, timeout=120)
      response.raise_for_status()

      #print(response)
      print("Function worked well")
      retorno = True
    except requests.exceptions.HTTPError as errh:
        print(errh)
        print("Error type 1, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
        print("Error type 2, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.Timeout as errt:
        print(errt)
        print("Error type 3, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.RequestException as err:
        print(err)
        print("Error type 4, sleeping and retrying")
        time.sleep(1)

  print("Left loop")
  end = time.time()
  print("End time send_agent_to_alive: "+str(end - start))
  return retorno

def send_agent_to_router(agent_id, data, path):
  """ Function used by NetLogo, to send agents to the platform. It removes an agent from the simulation and sends it to the API (to be inserted in the router table). Calls the model_to_router endpoint on API """
  start = time.time()
  host, port = host_port()
  print("Start time send_agent_to_router: "+str(start))
  retorno = False
  while retorno == False:
    try:
      # response = requests.post('http://localhost:5000/api/v1/resources/model_to_router', json = {"agent_id":agent_id, "data":data, "path":path}, timeout=5)
      #response = requests.post('http://api:5000/api/v1/resources/model_to_router', json = {"agent_id":agent_id, "data":data, "path":path}, timeout=5)
      
      #response = requests.post('http://api:5000/api/v1/resources/model_to_router', json = {"agent_id":agent_id, "data":data, "path":path})
      response = requests.post('http://'+host+':'+port+'/api/v1/resources/model_to_router', json = {"agent_id":agent_id, "data":data, "path":path}, timeout=120)
      response.raise_for_status()

      #print(response)
      print("Function worked well")
      retorno = True
    except requests.exceptions.HTTPError as errh:
        print(errh)
        print("Error type 1, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
        print("Error type 2, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.Timeout as errt:
        print(errt)
        print("Error type 3, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.RequestException as err:
        print(err)
        print("Error type 4, sleeping and retrying")
        time.sleep(1)

  print("Left loop")
  end = time.time()
  print("End time send_agent_to_router: "+str(end - start))
  return retorno

def receiving_agents(modelo):
  """ Function used by NetLogo to receive agents from the platform. It receives an agent from the API and inserts it into the simulation. Calls the check_new_agents endpoint on API """
  start = time.time()
  host, port = host_port()
  print("Start time receiving_agents: "+str(start))
  str1 = ''
  return_list = []
  retorno = False
  while retorno == False:
    try:
      # response = requests.get('http://localhost:5000/api/v1/resources/check_new_agents', params={"model":modelo}, timeout=5)
      # response = requests.get('http://api:5000/api/v1/resources/check_new_agents', params={"model":modelo}, timeout=5)
      
      #response = requests.get('http://api:5000/api/v1/resources/check_new_agents', params={"model":modelo})
      response = requests.get('http://'+host+':'+port+'/api/v1/resources/check_new_agents', params={"model":modelo}, timeout=120)
      response.raise_for_status()
      return_list = response.json()

      print("Function worked well")
      retorno = True    
      #str1 = ''.join(str(e) for e in response.json())
    except requests.exceptions.HTTPError as errh:
        print(errh)
        print("Error type 1, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
        print("Error type 2, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.Timeout as errt:
        print(errt)
        print("Error type 3, sleeping and retrying")
        time.sleep(1)
    except requests.exceptions.RequestException as err:
        print(err)
        print("Error type 4, sleeping and retrying")
        time.sleep(1)
  # return str1
  print("Left loop")
  end = time.time()
  print("End time receiving_agents: "+str(end - start))
  return return_list

# def process_agents_on_router():
#   #router_type = "random"
#   router_type = "sequential"
#   print("Router type:"+router_type)
#   connected = False
#   while (connected == False):
#     try:
#       cnx = mysql.connector.connect(user='root', password='root',
#                                host='db',
#                                database='MYSQL_DATABASE')
#       connected = cnx.is_connected()
#     except:
#       print("Error connecting to the database")
#       time.sleep(3)
#   cursor = cnx.cursor()

#   # print("Connected to the DB successfully")

#   if(router_type == "random"):
#     order = "RAND()"
#   elif(router_type == "sequential"):
#     order = "created_at ASC"

#   query = ("SELECT id, agent_id, data, path, processed FROM router "
#             "WHERE processed = 0 ORDER BY "+order)
#   modelos_list = ["m1", "m2", "m3"]
#   #model_to_send = random.choice(modelos_list)
#   cursor.execute(query)


#   return_list = []
#   delete_list = []

#   for (id, agent_id, data, path, processed) in cursor:
#     return_list.append([agent_id, data, path, id])

#   cursor.close()
#   # modelos_list = ["m1", "m2", "m3"]

#   cnx.close()

#   for tupla in return_list:
#     cnx = mysql.connector.connect(user='root', password='root',
#                                host='db',
#                                database='MYSQL_DATABASE')
#     cursor = cnx.cursor()
#     cnx.start_transaction()

#     model_to_send = random.choice(modelos_list)

#     agent_id = str(tupla[0])
#     data = tupla[1]
#     path = tupla[2]
#     tupla_id = str(tupla[3])
#     processed = str(0)

#     sql1 = "INSERT INTO "+model_to_send+ " (agent_id, data, path, processed) "+"VALUES ('"+agent_id+"', '"+data+"', '"+path+"', '"+processed+"');"
#     sql2 = "UPDATE router SET processed = 1 WHERE id = "+tupla_id+"; "
#     try:
#       cursor.execute(sql1)
#       cursor.execute(sql2)
#       # Make sure data is committed to the database
#       cnx.commit()
#       print("Agent_id: "+agent_id+" sended to model "+model_to_send)
#     # except mysql.connector.ProgrammingError as err:
#     except mysql.connector.Error as err:
#       print("Failed inserting on database: {}".format(err))
#       print("Rolling back ...")
#       print(e)
#       db.rollback()  # rollback changes
#       testing_exception(err)
#     # except errors.Error as e:
#     #   print("Rolling back ...")
#     #   print(e)
#     #   db.rollback()  # rollback changes
#     finally:
#       cursor.close()
#       cnx.close()

# def backup_funcional_process_agents_on_router():
#   while True:
#     cnx = mysql.connector.connect(user='root', password='root',
#                                  host='db',
#                                  database='MYSQL_DATABASE')
#     cursor = cnx.cursor()
#     query = ("SELECT id, agent_id, data, path, processed FROM router "
#               "WHERE processed = 0")
#     cursor.execute(query)


#     return_list = []
#     delete_list = []

#     for (id, agent_id, data, path, processed) in cursor:
#       return_list.append([agent_id, data, path, id])

#     cursor.close()
#     modelos_list = ["m1", "m2", "m3"]

#     cnx.close()

#     for tupla in return_list:
#       cnx = mysql.connector.connect(user='root', password='root',
#                                  host='db',
#                                  database='MYSQL_DATABASE')
#       cursor = cnx.cursor()
#       cnx.start_transaction()

#       model_to_send = random.choice(modelos_list)

#       agent_id = str(tupla[0])
#       data = tupla[1]
#       path = tupla[2]
#       tupla_id = str(tupla[3])
#       processed = str(0)

#       sql1 = "INSERT INTO "+model_to_send+ " (agent_id, data, path, processed) "+"VALUES ('"+agent_id+"', '"+data+"', '"+path+"', '"+processed+"');"
#       sql2 = "UPDATE router SET processed = 1 WHERE id = "+tupla_id+"; "
#       try:
#         cursor.execute(sql1)
#         cursor.execute(sql2)
#         # Make sure data is committed to the database
#         cnx.commit()
#         print("Agent_id: "+agent_id+" sended to model "+model_to_send)
#       # except mysql.connector.ProgrammingError as err:
#       except mysql.connector.Error as err:
#         print("Failed inserting on database: {}".format(err))
#         print("Rolling back ...")
#         print(e)
#         db.rollback()  # rollback changes
#         testing_exception(err)
#       # except errors.Error as e:
#       #   print("Rolling back ...")
#       #   print(e)
#       #   db.rollback()  # rollback changes
#       finally:
#         cursor.close()
#         cnx.close()


#   # while True:
#   #   cnx = mysql.connector.connect(user='root', password='root',
#   #                                host='db',
#   #                                database='MYSQL_DATABASE')
#   #   cursor = cnx.cursor()
#   #   query = ("SELECT id, agent_id, data, path, processed FROM router "
#   #             "WHERE processed = 0")
#   #   cursor.execute(query)


#   #   return_list = []
#   #   delete_list = []

#   #   for (id, agent_id, data, path, processed) in cursor:
#   #     return_list.append([agent_id, data, path, id])

#   #   cursor.close()
#   #   modelos_list = ["m1"]

#   #   for tupla in return_list:
#   #     cnx = mysql.connector.connect(user='root', password='root',
#   #                                host='db',
#   #                                database='MYSQL_DATABASE')
#   #     cursor = cnx.cursor()
#   #     cnx.start_transaction()

#   #     model_to_send = random.choice(modelos_list)

#   #     agent_id = str(tupla[0])
#   #     data = tupla[1]
#   #     path = tupla[2]
#   #     tupla_id = str(tupla[3])
#   #     processed = str(0)

#   #     sql1 = "INSERT INTO "+model_to_send+ " (agent_id, data, path, processed) "+"VALUES ('"+agent_id+"', '"+data+"', '"+path+"', '"+processed+"');"
#   #     sql2 = "UPDATE router SET processed = 1 WHERE id = "+tupla_id+"; "
#   #     try:
#   #       cursor.execute(sql1)
#   #       cursor.execute(sql2)
#   #       # Make sure data is committed to the database
#   #       cnx.commit()
#   #     except errors.Error as e:
#   #       db.rollback()  # rollback changes
#   #       print("Rolling back ...")
#   #       print(e)
#   #     finally:
#   #       cursor.close()
#   #       cnx.close()


# def print_request_to_register(model, qtd):

#   cnx = mysql.connector.connect(user='root', password='root',
#                                  host='db',
#                                  database='MYSQL_DATABASE')
#   retorno = False
#   for agent_id in range(1, qtd):
#     cursor = cnx.cursor()
#     # add_agent = ("INSERT INTO router "
#     #              "(agent_id, data) "
#     #              "VALUES (%s, %s)")
#     # data = [random.randint(5, 25) random.randint(1, 4) random.randint(1, 6)]
#     # data = []
#     # data.append(random.randint(5, 25))
#     # data.append(random.randint(1, 4))
#     # data.append(random.randint(1, 6))

#     data = "[" + str(random.randint(5, 25)) + " " + str(random.randint(1, 4)) + " " + str(random.randint(1, 6)) + "]"

#     print(data)

#     # data_agent = (agent_id, data)
#     sql1 = "INSERT INTO "+model+ " (agent_id, data) "+"VALUES ('"+str(agent_id)+"', '"+data+"');"

#     # # Insert new employee
#     # cursor.execute(add_employee, data_employee)
#     try:
#         # cursor.execute(add_agent, data_agent)
#         cursor.execute(sql1)
#         # Make sure data is committed to the database
#         cnx.commit()
#         retorno = True
#     except mysql.connector.Error as err:
#         print("Failed inserting on database: {}".format(err))
#         retorno = False
#     finally:
#         cursor.close()

#     if (retorno == False):
#         break

#   cnx.close()
#   return retorno

# def print_send_agent_to_router(agent_id, data, path):

#   cnx = mysql.connector.connect(user='root', password='root',
#                                  host='db',
#                                  database='MYSQL_DATABASE')
#   cursor = cnx.cursor()

#   # tomorrow = datetime.now().date() + timedelta(days=1)

#   print(agent_id)
#   print(data)
#   print(path)

#   # print(string_recebida)
#   # string_filtrada = string_recebida.split()
#   # for agent_id, data, path in string_filtrada:
#   #   print(agent_id)
#   #   print(data)
#   #   print(path)

#   add_agent = ("INSERT INTO router "
#                  "(agent_id, data, path) "
#                  "VALUES (%s, %s, %s)")

#   data_agent = (agent_id, data, path)

#   # # Insert new employee
#   # cursor.execute(add_employee, data_employee)
#   try:
#     cursor.execute(add_agent, data_agent)
#     # Make sure data is committed to the database
#     cnx.commit()
#     retorno = True
#   except mysql.connector.Error as err:
#     print("Failed inserting on database: {}".format(err))
#     retorno = False

#   # if (cursor.execute(add_employee, data_employee)):
#   #   print("dale")
#   # else:
#   #   print("dele")

#   # # Make sure data is committed to the database
#   # cnx.commit()

#   cursor.close()
#   cnx.close()
#   return retorno

# def print_receiving_agents(modelo):

#   return_list = []
#   to_update = []

#   cnx = mysql.connector.connect(user='root', password='root',
#                                  host='db',
#                                  database='MYSQL_DATABASE')
#   cursor = cnx.cursor()
#   query = ("SELECT id, agent_id, data, path, processed FROM "+modelo+" "
#             "WHERE processed = %s AND %s")

#   # print("modelo:"+modelo)
#   cursor.execute(query, (0, "1=1"))

#   for (id, agent_id, data, path, processed) in cursor:
#     print("id: {}, agent_id: {}, data: {}, path: {}, processed: {}".format(
#       id, agent_id, data, path, processed))
#     return_list.append([agent_id, data, path])
#     to_update.append(id)

#   cursor.close()

#   print(to_update)

#   for tupla in to_update:
#     cursor = cnx.cursor()
#     temporary_query = "UPDATE "+modelo+" SET processed = 1 WHERE id = "+str(tupla)+"; "
#     print("temporary query:"+temporary_query)
#     query = (temporary_query)
#     cursor.execute(temporary_query)
#     cnx.commit()
#     cursor.close()

#   # print("modelo:"+modelo)

#   cnx.close()

#   # for tupla in return_list:
#   #   print("tupla: "+tupla)
#   return return_list

# def print_send_function(string_to_send):
#     return "3"

# def print_process_agents_on_router():
#   #while True:
#   cnx = mysql.connector.connect(user='root', password='root',
#                                host='db',
#                                database='MYSQL_DATABASE')
#   cursor = cnx.cursor()
#   query = ("SELECT id, agent_id, data, path, processed FROM router "
#             "WHERE processed = 0")

#   # print("modelo:"+modelo)
#   cursor.execute(query)


#   return_list = []
#   delete_list = []

#   print("lendo router: ")

#   for (id, agent_id, data, path, processed) in cursor:
#     print("id: {}, agent_id: {}, data: {}, path: {}, processed: {}".format(
#       id, agent_id, data, path, processed))
#     return_list.append([agent_id, data, path, id])


#   print(return_list)

#   cursor.close()

#   # cursor.close()
#   # cnx.close()

#   # modelos_list = ["m1","m2","m3"]
#   modelos_list = ["m1"]

#   for tupla in return_list:
#     cnx = mysql.connector.connect(user='root', password='root',
#                                host='db',
#                                database='MYSQL_DATABASE')
#     cursor = cnx.cursor()
#     cnx.start_transaction()

#     model_to_send = random.choice(modelos_list)

#     print("tupla: "+str(tupla[0])+" indo para modelo : "+model_to_send)

#     agent_id = str(tupla[0])
#     data = tupla[1]
#     path = tupla[2]
#     tupla_id = str(tupla[3])
#     processed = str(0)

#     sql1 = "INSERT INTO "+model_to_send+ " (agent_id, data, path, processed) "+"VALUES ('"+agent_id+"', '"+data+"', '"+path+"', '"+processed+"');"
#     sql2 = "UPDATE router SET processed = 1 WHERE id = "+tupla_id+"; "


#     # full_query = "START TRANSACTION; "
#     # full_query += "INSERT INTO "+model_to_send+ " (data, processed) "+"VALUES ('"+tupla[0]+"' ,0); "
#     # # full_query += "DELETE FROM router WHERE id = "+str(tupla[1])+"; "
#     # full_query += "UPDATE router SET processed = 1 WHERE id = "+str(tupla[1])+"; "
#     # full_query += "COMMIT;"

#     # full_query = "START TRANSACTION; "
#     # full_query += "INSERT INTO "+model_to_send+ " (data, processed) "+"VALUES ('"+tupla[0]+"' ,0); "
#     # # full_query += "DELETE FROM router WHERE id = "+str(tupla[1])+"; "
#     # full_query += "UPDATE router SET processed = 1 WHERE id = "+str(tupla[1])+"; "
#     # full_query += "COMMIT;"

#     # full_query = "START TRANSACTION; "
#     # full_query += "INSERT INTO "+model_to_send+ " (data, processed) "+"VALUES (%s, %s); "
#     # full_query += "DELETE FROM router WHERE id = %s "
#     # full_query += "COMMIT;"

#     # print("full query: "+full_query)
#     # add_employee = ("INSERT INTO "+model_to_send+ " "
#     #                "(data, processed) "
#     #                "VALUES (%s, %s)")

#     # data_employee = (tupla[0], 0, str(tupla[1]))

#     # # Insert new employee
#     # cursor.execute(add_employee, data_employee)
#     try:
#       # cursor.execute(full_query, data_employee)
#       cursor.execute(sql1)
#       cursor.execute(sql2)
#       # Make sure data is committed to the database
#       cnx.commit()
#     except errors.Error as e:
#       db.rollback()  # rollback changes
#       print("Rolling back ...")
#       print(e)
#     finally:
#       cursor.close()
#       cnx.close()
    
#   # cnx.close()

#   # cursor.close()
#   # cnx.close()

#   # for tupla in return_list:
#   #   print("tupla: "+tupla)
#   return return_list