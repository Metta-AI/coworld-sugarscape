import time
import requests

def main():
    """ Loop function that receives and process agents in the router """
    print ('Starting router...')
    while True:
        retorno = False
        while retorno == False:
            try:
                response = requests.get('http://api:5000/api/v1/resources/process_agents_on_router')
                print('Response from API: ' + response.text)
                response.raise_for_status()
                time.sleep(5)
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

if __name__ == '__main__':
    main()