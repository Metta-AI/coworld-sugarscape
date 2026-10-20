package mylib;

import jason.*;
import jason.runtime.*;
import jason.asSemantics.*;
import jason.asSyntax.*;

import java.nio.file.Path;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.io.*;
import java.util.List;

import java.nio.charset.StandardCharsets;
import java.nio.file.StandardOpenOption;
// PRO DB
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

import java.util.ArrayList;

import java.util.*;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;
import javax.script.ScriptEngine;
import javax.script.ScriptEngineManager;
import javax.script.ScriptException;

import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Scanner;


import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;



import java.util.stream.Stream;

public class my_create_ag extends DefaultInternalAction {

    @Override
    public Object execute(TransitionSystem ts, Unifier un, Term[] args) throws Exception {

        String host = System.getenv("host");

        RuntimeServices rs = RuntimeServicesFactory.get();

        Collection<String> names = rs.getAgentsNames();
        System.out.println("All agents at the moment:");
        System.out.println(names);

        String y[] = names.toArray(new String[names.size()]);

        Boolean has_df = (Arrays.asList(y)).contains("df");
        if ((!has_df && names.size() == 3) || (has_df && names.size() == 4)) {
            System.out.println("3 agents and no df, checking if there is a new agent on API to be created...");

            try {
                URL url = new URL("http://"+host+":5000/api/v1/resources/check_new_agents_1?model=m3");
                String inline = "";
                Scanner scanner = new Scanner(url.openStream());

                //Write all the JSON data into a string using a scanner
                while (scanner.hasNext()) {
                    inline += scanner.nextLine();
                }

                //Close the scanner
                scanner.close();

                //Using the JSON simple library parse the string into a json object
                JSONParser parse = new JSONParser();

                JSONParser parser = new JSONParser();
                JSONArray arr  = (JSONArray) parser.parse(inline);

                if (arr.size() > 0){
                    System.out.println("New agents");
                    for (int i = 0; i < arr.size(); i++) {
                        JSONArray arr2  = (JSONArray) arr.get(i);

                        String agent_id = arr2.get(0).toString();
                        String agent_stats = arr2.get(1).toString();
                        String agent_path = arr2.get(2).toString();

                        System.out.println("ID: " + agent_id);
                        System.out.println("Stats: " + agent_stats);
                        System.out.println("Path: " + agent_path);

                        JSONParser parser2 = new JSONParser();
                        JSONArray arr3  = (JSONArray) parser2.parse(arr2.get(1).toString());

                        String sugar = arr3.get(0).toString();
                        String metabolism = arr3.get(1).toString();
                        String vision = arr3.get(2).toString();

                        System.out.println("Sugar: " + sugar);
                        System.out.println("Metabolism: " + metabolism);
                        System.out.println("Vision: " + vision);

                        Settings s = new Settings();

                        char ch='"';
                        String bels = "agent_id("+agent_id+")";
                        bels = bels + ",path("+ ch + agent_path + ch + ")";
                        bels = bels + ", sugar("+sugar+"), metabolism("+metabolism+"), vision("+vision+")";
                        System.out.println("Vai criar o agente com os beliefs: "+bels);

                        s.addOption(Settings.INIT_BELS, bels);
                        s.addOption(Settings.INIT_GOALS, "jcm::focus_env_art([art_env(mining,m2view,default)],5)");


                        try {
                            String asl_file_name = "list/"+agent_id+".asl";

                            if (!Files.exists(Paths.get("src/agt/"+asl_file_name))){
                                asl_file_name = "default_agent.asl";
                            }

                            System.out.println("asl_file_name: "+asl_file_name);

                            rs.createAgent(agent_id, asl_file_name, null, null, null, s, ts.getAg());
                            rs.startAgent(agent_id);
                            System.out.println("Agent created by custom file");
                        } catch (Exception e) {
                            e.printStackTrace();
                        }
                    } 
                } else {
                    //System.out.println("No agents to join");
                }

            } catch (Exception e) {
                e.printStackTrace();
            }
        }

        // everything ok, so returns true
        return true;
    }
}