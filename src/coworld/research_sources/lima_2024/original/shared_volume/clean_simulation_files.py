import os
import glob
import time

def main():
    """ Code used to clear simulation files. At this moment, clears output and alive txt files from every NetLogo's models """
    files_to_delete = [
        "/shared_volume/netlogo_output/m1_output.txt",
        "/shared_volume/netlogo_output/m1_alive.txt",
        "/shared_volume/netlogo_output/m2_output.txt",
        "/shared_volume/netlogo_output/m2_alive.txt"
    ]

    file_path = "/shared_volume/jacamo/jacamo_model/src/agt/list/"
    
    for clean_up in glob.glob(file_path+'*.*'):
        if not clean_up.endswith('.gitkeep'):
            files_to_delete.append(clean_up)

    for filename in files_to_delete:
        if os.path.exists(filename):
            print("Deleting file: "+filename)
            os.remove(filename)
        else:
            print(filename + " does not exists")

if __name__ == '__main__':
    main()