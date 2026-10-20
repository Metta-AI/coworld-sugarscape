import requests

def main():
    """ Python code used by NetLogo to access the API """

    try:
        #request_to_register('" ("m1") "'" "," (1) ", " (400) ")
        response = requests.post('http://localhost:5000/api/v1/resources/request_to_register', json = {"model":"m1", "min":1, "max":400}, timeout=5)
        response.raise_for_status()

        print(response)
        # Code here will only run if the request is successful
    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)

    try:
        response = requests.post('http://localhost:5000/api/v1/resources/model_to_router', json = {"agent_id":"12", "data":"[1 2 3]", "path":"1-1"}, timeout=5)
        response.raise_for_status()

        print(response)
        # Code here will only run if the request is successful
    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)

    #from db_python_netlogo import receiving_agents
    #receiving_agents('" ("m1") "')
    try:
        #request_to_register('" ("m1") "'" "," (1) ", " (400) ")
        response = requests.get('http://localhost:5000/api/v1/resources/check_new_agents', params={"model":"m1"}, timeout=5)
        response.raise_for_status()
        
        str1 = ''.join(str(e) for e in response.json())
        print(str1)
    except requests.exceptions.HTTPError as errh:
        print(errh)
    except requests.exceptions.ConnectionError as errc:
        print(errc)
    except requests.exceptions.Timeout as errt:
        print(errt)
    except requests.exceptions.RequestException as err:
        print(err)


if __name__ == '__main__':
    main()