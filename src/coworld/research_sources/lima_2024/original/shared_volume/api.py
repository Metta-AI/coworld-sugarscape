import flask
from flask import request, jsonify
#import sqlite3

import mysql.connector
from mysql.connector import errorcode

import random

import os
import re
import json

import string

import time

from re import search
import requests

#https://programminghistorian.org/en/lessons/creating-apis-with-python-and-flask

#app = flask.Flask(__name__)

app = flask.Flask(__name__, static_url_path='/', static_folder='_build/html/')


@app.route('/')
@app.route('/<path:path>')
def serve_sphinx_docs(path='index.html'):
    return app.send_static_file(path)


#app = flask.Flask(__name__, static_url_path='/shared_volume/docs/_build/html')
app.config["DEBUG"] = True

docker_debugger = True

# @app.route('/docs', defaults = {'filename': 'index.html'})
# @app.route('/docs/<path:filename>')
# def web_docs(filename):
#   print(filename)
#   path = os.path.join('/shared_volume/docs/_build/html', filename)
#   return flask.send_file(path)
#   #path = os.path.join('/shared_volume/docs/_build/html', filename)
#   #print(path)
#   #print("file? "+str(os.path.isfile(path)))
#   #return app.send_static_file(path)
def connect_to_db():
  """ Function used to let the API connect to DB """
  connected = False
  while (connected == False):
    try:
      cnx = mysql.connector.connect(user='root', password='root',
                                     host='db',
                                     database='MYSQL_DATABASE')
      cursor = cnx.cursor()
      connected = cnx.is_connected()
    except:
      if docker_debugger: print("**Error** Error connecting to the DB")
      time.sleep(3)

  return cnx, cursor


@app.errorhandler(404)
def page_not_found(e):
  """ Function that handles 404 requests to the API """
  #test
  return "<h1>404</h1><p>The resource could not be found.</p>", 404

@app.route('/api/v1/resources/output_php', methods=['GET'])
def output_php():
  """ Function that sends to the PHP code the data to create the list of agents of the simulation """
  query_parameters = request.args
  model = query_parameters.get('model')

  return_list = []
  to_update = []

  cnx, cursor = connect_to_db()

  query = "SELECT MAX(id) AS id, agent_id, MAX(data) AS data, MAX(path) AS path, MAX(processed) AS processed FROM "+model+" GROUP BY agent_id ORDER BY agent_id ASC";
  cursor.execute(query)

  for (id, agent_id, data, path, processed) in cursor:
    return_list.append([agent_id, data, path, processed])
    to_update.append(id)

  cursor.close()

  cnx.close()
  if docker_debugger: print("Sending: "+str(return_list))
  return jsonify(return_list)

@app.route('/api/v1/resources/check_new_agents_1', methods=['GET'])
def check_new_agentss_1():
  """ Checks if there is any new agent to insert in the simulation. Return a single agent """

  query_parameters = request.args
  model = query_parameters.get('model')

  return_list = []
  to_update = []

  cnx, cursor = connect_to_db()

  query = ("SELECT id, agent_id, data, path, processed FROM "+model+" "
            "WHERE processed = 0 ORDER BY created_at ASC LIMIT 1")

  cursor.execute(query)

  for (id, agent_id, data, path, processed) in cursor:
    return_list.append([agent_id, data, path])
    to_update.append(id)

  cursor.close()

  for tupla in to_update:
    try:
      cursor = cnx.cursor()
      temporary_query = "UPDATE "+model+" SET processed = 1 WHERE id = "+str(tupla)+"; "
      query = (temporary_query)
      cursor.execute(temporary_query)
      cnx.commit()
    except mysql.connector.Error as err:
      if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
    finally:
      cursor.close()

  cnx.close()
  if docker_debugger: print("Sending: "+str(return_list))
  return jsonify(return_list)

@app.route('/api/v1/resources/process_agents_on_router', methods=['GET'])
def process_agents_on_router():
  """ Function used by the router, that removes an agent from router and inserts it in a simulation, accordingly to the router type """

  router_type = "sequential"
  if docker_debugger: print("Router type:"+router_type)

  cnx, cursor = connect_to_db()
  cursor = cnx.cursor()

  if(router_type == "random"):
    order = "RAND()"
  elif(router_type == "sequential"):
    order = "created_at ASC"

  query = ("SELECT id, agent_id, data, path, processed FROM router "
            "WHERE processed = 0 ORDER BY "+order)
  models_list = ["m1", "m2", "m3"]
  cursor.execute(query)


  return_list = []
  delete_list = []

  for (id, agent_id, data, path, processed) in cursor:
    return_list.append([agent_id, data, path, id])

  cursor.close()

  cnx.close()

  if (len(return_list) == 0):
    if docker_debugger: print("No agents to be processed at the moment.")
  else:
    for tupla in return_list:
      cnx, cursor = connect_to_db()
      cnx.start_transaction()

      model_to_send = random.choice(models_list)

      agent_id = str(tupla[0])
      data = tupla[1]
      path = tupla[2]
      tupla_id = str(tupla[3])
      processed = str(0)

      return_list = []

      sql1 = "INSERT INTO "+model_to_send+ " (agent_id, data, path, processed) "+"VALUES ('"+agent_id+"', '"+data+"', '"+path+"', '"+processed+"');"
      sql2 = "UPDATE router SET processed = 1 WHERE id = "+tupla_id+"; "
      try:
        cursor.execute(sql1)
        cursor.execute(sql2)
        # Make sure data is committed to the database
        cnx.commit()
        if docker_debugger: print("Agent_id: "+agent_id+" sended to model "+model_to_send)
        new_value = {'id': str(agent_id), 'model': model_to_send}
        return_list.append(new_value)
      except mysql.connector.Error as err:
        if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
        if docker_debugger: print("**Error** Rolling back ...")
        if docker_debugger: print(e)
        db.rollback()  # rollback changes
        new_value = {'id': str(agent_id), 'model': "ERROR"}
        return_list.append(new_value)
      finally:
        cursor.close()
        cnx.close()
  return jsonify(return_list)


@app.route('/api/v1/resources/check_new_agents', methods=['GET'])
def check_new_agentss():
  """ Checks if there is any new agent to insert in the simulation. Return multiple agents (all available at the moment) """

  query_parameters = request.args
  model = query_parameters.get('model')

  return_list = []
  #to_update = []

  cnx, cursor = connect_to_db()
  query = ("SELECT id, agent_id, data, path, processed FROM "+model+" "
            "WHERE processed = 0")

  cursor.execute(query)
  id_list = ""
  for (id, agent_id, data, path, processed) in cursor:
    return_list.append([agent_id, data, path])
    id_list += str(id)+"," 
  if(id_list != ""):
    id_list = id_list[:-1]

  if docker_debugger: print("id_list: "+id_list)

  cursor.close()

  if (id_list != ""):
    try:
      cursor = cnx.cursor()
      temporary_query = "UPDATE "+model+" SET processed = 1 WHERE id IN ("+id_list+");"
      if docker_debugger: print("temporary query: "+temporary_query)
      query = (temporary_query)
      cursor.execute(temporary_query)
      cnx.commit()
    except mysql.connector.Error as err:
      if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
    finally:
      cursor.close()

  cnx.close()
  if docker_debugger: print("Sending: "+str(return_list))
  return jsonify(return_list)

@app.route('/api/v1/resources/sanity_test', methods=['GET'])
def sanity_test():
  """
  Sanity test that tests if every agent (at the moment, from 1 to 799):
  (i) appears in the following situations:
  - all models table, where processed = 0
  - alive agents table, from every model
  - last one from m3 (current alive agent in JaCaMo)
  - in router table (router queue)
  (ii) appears in the previous scenario just once
  (iii) if every agent from m3 (except for the alive) has a .asl file
  """

  query_parameters = request.args
  model = query_parameters.get('model')

  return_list = []

  m1_alive = []
  m2_alive = []
  m3_alive = []

  m1_on_db = []
  m2_on_db = []
  m3_on_db = []

  on_router = []

  cnx, cursor = connect_to_db()

  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM m1 WHERE processed = 0 ORDER BY agent_id")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    m1_on_db.append(agent_id_part)
  cursor.close()

  if docker_debugger: print("m1_on_db:")
  if docker_debugger: print(m1_on_db)

  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM m2 WHERE processed = 0 ORDER BY agent_id")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    m2_on_db.append(agent_id_part)
  cursor.close()

  if docker_debugger: print("m2_on_db:")
  if docker_debugger: print(m2_on_db)

  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM m3 WHERE processed = 0 ORDER BY agent_id")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    m3_on_db.append(agent_id_part)
  cursor.close()

  if docker_debugger: print("m3_on_db:")
  if docker_debugger: print(m3_on_db)

  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM alive_agents WHERE model = 'm1' ORDER BY agent_id")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    m1_alive.append(agent_id_part)
  cursor.close()

  if docker_debugger: print("m1_alive:")
  if docker_debugger: print(m1_alive)

  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM alive_agents WHERE model = 'm2' ORDER BY agent_id")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    m2_alive.append(agent_id_part)
  cursor.close()

  if docker_debugger: print("m2_alive:")
  if docker_debugger: print(m2_alive)

  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM m3 WHERE processed = 1 ORDER BY id DESC LIMIT 1")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    m3_alive.append(agent_id_part)
  cursor.close()

  if docker_debugger: print("m3_alive:")
  if docker_debugger: print(m3_alive)

  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM router WHERE processed = 0 ORDER BY agent_id")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    on_router.append(agent_id_part)
  cursor.close()

  if docker_debugger: print("on_router:")
  if docker_debugger: print(on_router)

  return_list = []

  # m3_on_db.remove(8)
  # m3_on_db.remove(19)

  if docker_debugger: print("-----------------------TEST-----------------------")
  # Test if all agent_id from 1 to 799 is in any of the normal conditions
  for x in range(1, 800):
    if x not in m1_alive and x not in m2_alive and x not in m3_alive and x not in m1_on_db and x not in m2_on_db and x not in m3_on_db and x not in on_router:
      if docker_debugger: print("**Error** "+str(x)+" not found")
      return_list.append({'id': x, 'error': "not found"})

  # https://stackoverflow.com/questions/4446380/python-check-the-occurrences-in-a-list-against-a-value
  # Test for duplicated values
  lst = m1_alive + m2_alive + m3_alive + m1_on_db + m2_on_db + m3_on_db + on_router

  # lst.append(11)
  # lst.append(700)


  count={}
  for item in lst:
    if(lst.count(item) != 1):
      if docker_debugger: print("**Error** Error on item: "+str(item))
      new_value = {'id': str(item), 'error': "duplicated"}
      if(new_value not in return_list):
        return_list.append(new_value)


  # Test if m3 tuples has files:

  m3_processed_agents = []
  cursor = cnx.cursor()
  query = ("SELECT agent_id FROM m3 WHERE processed = 1 ORDER BY agent_id")
  cursor.execute(query)
  for agent_id in cursor:
    string1 = str(agent_id)
    agent_id_part = int(re.search(r'\d+', string1).group())
    m3_processed_agents.append(agent_id_part)
  cursor.close()

  #Alive agent
  m3_alive_agent = m3_alive[0]

  for agent_id in m3_processed_agents:
    fname = "/shared_volume/jacamo/jacamo_model/src/agt/list/"+str(agent_id)+".asl"
    if(not os.path.isfile(fname)):
      if(agent_id != m3_alive_agent):
        if docker_debugger: print("**Error** "+str(agent_id)+ " asl file does not exists")
        new_value = {'id': str(agent_id), 'error': "asl file does not exists"}
        return_list.append(new_value)

  cnx.close()

  return jsonify(return_list)

@app.route('/api/v1/resources/sanity_test_agent_path_history', methods=['GET'])
def sanity_test_agent_path_history():
  """  Sanity test: tests the path from a single agent """

  query_parameters = request.args
  search_agent_id = query_parameters.get('agent_id')

  if docker_debugger: print("search_agent_id: " + str(search_agent_id))

  return_list = []
  m1_on_db = []

  cnx, cursor = connect_to_db()

  cursor = cnx.cursor()
  # query = ("SELECT agent_id FROM m1 WHERE processed = 0 ORDER BY agent_id")
  # cursor.execute(query)
  # for agent_id in cursor:
  #   string1 = str(agent_id)
  #   agent_id_part = int(re.search(r'\d+', string1).group())
  #   m1_on_db.append(agent_id_part)
  # cursor.close()

  # cursor = cnx.cursor()

  query = "SELECT * from router where agent_id = " + str(search_agent_id) + " ORDER BY LENGTH(path) ASC";
  if docker_debugger: print(query)
  	
  cursor.execute(query)
  for id, agent_id, data, path, asl_file_path, processed, created_at, updated_at in cursor:

    if docker_debugger: print(agent_id)
    new_value = {'path': path}
    return_list.append(new_value)
  cursor.close()

  cnx.close()
  
  # if(len(return_list) == 0):
  #   new_value = {}
  #   return_list.append(new_value)

  return jsonify(return_list)


@app.route('/api/v1/resources/sanity_test_recheck_agent_path', methods=['GET'])
def sanity_test_recheck_agent_path():
  """ Sanity test: for every agent in m1, m2 and m3, tests if the path has a continous cycle """

  query_parameters = request.args
  return_list = []

  cnx, cursor = connect_to_db()

  cursor = cnx.cursor()

  query = "SELECT agent_id, path from m1 ORDER BY path ASC";
  if docker_debugger: print(query)

  prev_path = ""    
  cursor.execute(query)
  for agent_id, path in cursor:
    if (prev_path == ""):
      continue
    if (not search(prev_path, path)):
      new_value = {'agent_id': agent_id, 'path': path}
      return_list.append(new_value)
    prev_path = path

  query = "SELECT agent_id, path from m2 ORDER BY path ASC";
  if docker_debugger: print(query)

  prev_path = ""    
  cursor.execute(query)
  for agent_id, path in cursor:
    if (prev_path == ""):
      continue
    if (not search(prev_path, path)):
      new_value = {'agent_id': agent_id, 'path': path}
      return_list.append(new_value)
    prev_path = path

  query = "SELECT agent_id, path from m3 ORDER BY path ASC";
  if docker_debugger: print(query)

  prev_path = ""    
  cursor.execute(query)
  for agent_id, path in cursor:
    if (prev_path == ""):
      continue
    if (not search(prev_path, path)):
      new_value = {'agent_id': agent_id, 'path': path}
      return_list.append(new_value)
    prev_path = path
  cursor.close()

  cnx.close()

  return jsonify(return_list)


@app.route('/api/v1/resources/sanity_test_agent_to_jacamo_without_asl_file', methods=['GET'])
def sanity_test_agent_to_jacamo_without_asl_file():
  """ Sanity test: tests if every agent from router, already processed, has a .asl file """

  query_parameters = request.args
  #search_agent_id = query_parameters.get('model')
  model = "m3"

  if docker_debugger: print("model: " + str(model))

  return_list = []

  cnx, cursor = connect_to_db()

  query = "SELECT agent_id, path FROM router WHERE processed = 1 AND path LIKE '%3%' ORDER BY agent_id ASC";
  print(query)
  cursor.execute(query)

  for (agent_id,path) in cursor:
    fname = "/shared_volume/jacamo/jacamo_model/src/agt/list/"+str(agent_id)+".asl"
    if(not os.path.isfile(fname)):
      if docker_debugger: print("**Error** "+str(agent_id)+ " asl file does not exists")
      new_value = {'id': str(agent_id), 'error': "asl file does not exists"}
      return_list.append(new_value)

  cursor.close()
  cnx.close()
  
  # if(len(return_list) == 0):
  #   new_value = {}
  #   return_list.append(new_value)

  return jsonify(return_list)


@app.route('/api/v1/resources/sanity_test_list', methods=['GET'])
def sanity_test_list():
  """ Sanity test: call all previous sanity test in a single route """

  return_list = []
  routes = [
        'http://api:5000/api/v1/resources/sanity_test',
        'http://api:5000/api/v1/resources/sanity_test_recheck_agent_path',
        'http://api:5000/api/v1/resources/sanity_test_agent_to_jacamo_without_asl_file'
  ]

  for route in routes:
    print("route: "+route)
    response = requests.get(route)
    print('Response from API: ' + response.text)
    if response.status_code == requests.codes.ok:
      if(response.json() != []):
        return_list.append(response.json())

  # response = requests.get('http://api:5000/api/v1/resources/sanity_test')
  # print('Response from API: ' + response.text)
  # if response.status_code == requests.codes.ok:
  #   if(response.json() != []):
  #     return_list.append(response.json())

  # # response = requests.get('http://api:5000/api/v1/resources/sanity_test_agent_path_history')
  # # print('Response from API: ' + response.text)
  # # if response.status_code == requests.codes.ok:
  # #   return_list.append(response.json())

  # response = requests.get('http://api:5000/api/v1/resources/sanity_test_recheck_agent_path')
  # print('Response from API: ' + response.text)
  # if response.status_code == requests.codes.ok:
  #   if(response.json() != []):
  #     return_list.append(response.json())

  # response = requests.get('http://api:5000/api/v1/resources/sanity_test_agent_to_jacamo_without_asl_file')
  # print('Response from API: ' + response.text)
  # if response.status_code == requests.codes.ok:
  #   if(response.json() != []):
  #     return_list.append(response.json())

  # print(type(str(sanity_test())))

  # retorno = json.loads(sanity_test())
  # print("retorno: "+str(retorno))
  # #retorno = sanity_test_agent_path_history()
  # #print("retorno: "+str(retorno))
  # retorno = json.loads(sanity_test_recheck_agent_path())
  # print("retorno: "+str(retorno))
  # retorno = json.loads(sanity_test_agent_to_jacamo_without_asl_file())
  # print("retorno: "+str(retorno))

  # return_list.append(sanity_test())
  # #return_list.append(sanity_test_agent_path_history())
  # return_list.append(sanity_test_recheck_agent_path())
  # return_list.append(sanity_test_agent_to_jacamo_without_asl_file())

  # print("return_list: "+str(return_list))


  return jsonify(return_list)



@app.route('/api/v1/resources/register_agents_on_platform', methods=['POST'])
def register_agents_on_platform():
  """ Route used to register agents on the platform (performed by register) """
  seed = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(5))
  start = time.time()
  if docker_debugger: print("Start time request_to_register: "+str(start) +" with seed: "+seed)
  json_data = request.get_json()
  if docker_debugger: print(json_data)
  model = json_data['model']
  model_number = model[1:]
  min = json_data['min']
  max = json_data['max']

  cnx, cursor = connect_to_db()

  return_value = False

  data = ""
  for agent_id in range(min, max):
    internal_data = "[" + str(random.randint(5, 25)) + " " + str(random.randint(1, 4)) + " " + str(random.randint(1, 6)) + "]"
    data += "('"+str(agent_id)+"', '"+internal_data+"', "+"''"+")"
    data += ", "

  data = data[:-2]
  if docker_debugger: print("data: "+data)

  try:
    cursor = cnx.cursor()
    sql1 = "INSERT INTO "+model+ " (agent_id, data, path) "+"VALUES "+data+";"
    if docker_debugger: print("sql1: "+sql1)
    cursor.execute(sql1)
    # Make sure data is committed to the database
    cnx.commit()
    return_value = True
  except mysql.connector.Error as err:
    if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
    return_value = False
  finally:
    cursor.close()

  cnx.close()

  end = time.time()
  if docker_debugger: print("End time request_to_register: "+str(end - start) +" with seed: "+seed)
  if(return_value):
    return 'true'
  else:
    return 'false'

@app.route('/api/v1/resources/request_to_register', methods=['POST'])
def request_to_register():
  """ Route used to register agents on the platform (performed by register) """
  seed = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(5))
  start = time.time()
  if docker_debugger: print("Start time request_to_register: "+str(start) +" with seed: "+seed)
  json_data = request.get_json()
  if docker_debugger: print(json_data)
  model = json_data['model']
  model_number = model[1:]
  min = json_data['min']
  max = json_data['max']

  cnx, cursor = connect_to_db()

  return_value = False
  for agent_id in range(min, max):
    cursor = cnx.cursor()

    data = "[" + str(random.randint(5, 25)) + " " + str(random.randint(1, 4)) + " " + str(random.randint(1, 6)) + "]"
    sql1 = "INSERT INTO "+model+ " (agent_id, data, path) "+"VALUES ('"+str(agent_id)+"', '"+data+"', "+"''"+");"
    try:
        cursor.execute(sql1)
        # Make sure data is committed to the database
        cnx.commit()
        return_value = True
    except mysql.connector.Error as err:
        if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
        return_value = False
    finally:
        cursor.close()

    if (return_value == False):
        break

  cnx.close()

  end = time.time()
  if docker_debugger: print("End time request_to_register: "+str(end - start) +" with seed: "+seed)
  if(return_value):
    return 'true'
  else:
    return 'false'

@app.route('/api/v1/resources/model_to_alive', methods=['POST'])
def model_to_alive():
  """ At the end of simulation, receives all agents from a model and inserts it into the alive_agent table """
  json_data = request.get_json()
  if docker_debugger: print(json_data)
  agent_id_list = json_data['agent_id']
  model = json_data['model']

  cnx, cursor = connect_to_db()

  query = "INSERT INTO alive_agents (agent_id, model) VALUES "
  for agent_id in agent_id_list.split(","):
    query += "("
    query += str(agent_id)
    query += ", "
    query += "'"+str(model)+"'"
    query += "), "
  #remove last comma and space
  query = query[:-2]
  #add ; to the end of query
  query += ";"

  if docker_debugger: print("Query: "+query)
  try:
    cursor.execute(query)
    # Make sure data is committed to the database
    cnx.commit()
    return_value = True
  except mysql.connector.Error as err:
    if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
    return_value = False

  cursor.close()
  cnx.close()
  if(return_value):
    return 'true'
  else:
    return 'false'

@app.route('/api/v1/resources/model_to_alive_single', methods=['POST'])
def model_to_alive_single():
  """ At the end of simulation, receives a single agent from a model and inserts it into the alive_agent table """
  json_data = request.get_json()
  if docker_debugger: print(json_data)
  agent_id = json_data['agent_id']
  model = json_data['model']

  cnx, cursor = connect_to_db()

  add_agent = ("INSERT INTO alive_agents "
                 "(agent_id, model) "
                 "VALUES (%s, %s)")

  data_agent = (agent_id, model)
  try:
    cursor.execute(add_agent, data_agent)
    # Make sure data is committed to the database
    cnx.commit()
    return_value = True
  except mysql.connector.Error as err:
    if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
    return_value = False

  cursor.close()
  cnx.close()
  if(return_value):
    return 'true'
  else:
    return 'false'



@app.route('/api/v1/resources/model_to_router', methods=['POST'])
def testing_sending():
  """ Receive an agent, from a model, and inserts it into the router table """
  json_data = request.get_json()
  if docker_debugger: print(json_data)
  agent_id = json_data['agent_id']
  data = json_data['data']
  path = json_data['path']

  cnx, cursor = connect_to_db()

  add_agent = ("INSERT INTO router "
                 "(agent_id, data, path) "
                 "VALUES (%s, %s, %s)")

  data_agent = (agent_id, data, path)
  try:
    cursor.execute(add_agent, data_agent)
    # Make sure data is committed to the database
    cnx.commit()
    return_value = True
  except mysql.connector.Error as err:
    if docker_debugger: print("**Error** Failed inserting on database: {}".format(err))
    return_value = False

  cursor.close()
  cnx.close()
  if(return_value):
    return 'true'
  else:
    return 'false'


if __name__ == '__main__':
  # testing connection before enabling API
  cnx_test, cursor_test = connect_to_db()
  app.run(host="0.0.0.0", port=5000)