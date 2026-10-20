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

import java.util.*;

import java.util.stream.Stream;


import org.apache.http.HttpEntity;
import org.apache.http.HttpResponse;
import org.apache.http.client.HttpClient;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.HttpClientBuilder;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;

public class my_delete_ag extends DefaultInternalAction {

    @Override
    public Object execute(TransitionSystem ts, Unifier un, Term[] args) throws Exception {

        try {
            // RuntimeServices provides services to create agents in the current platform (Local, JADE, JaCaMo, ...)
            RuntimeServices rs = RuntimeServicesFactory.get();

            String host = System.getenv("host");

            System.out.println("Executing JAVA custom code - delete");

            System.out.println("Java Args0 - agent_id: "+args[0]);
            System.out.println("Java Args1 - path: "+args[1]);
            System.out.println("Java Args2 - id: "+args[2]);
            System.out.println("Java Args3 - sugar: "+args[3]);
            System.out.println("Java Args4 - metabolism: "+args[4]);
            System.out.println("Java Args5 - vision: "+args[5]);

            // Tupla pro banco: agent_id, data(montado), path-3

            String tupla_agent_id = String.valueOf(args[0]);
            String tupla_data = "[" + String.valueOf(args[3]) + " " + String.valueOf(args[4]) + " " + String.valueOf(args[5]) + "]";
            String tupla_path = String.valueOf(args[1]) == "" ? "3" : String.valueOf(args[1]).replace("\"", "")+"-3";

            System.out.println("Tupla - agent_id: "+tupla_agent_id);
            System.out.println("Tupla - data: "+tupla_data);
            System.out.println("Tupla - path: "+tupla_path);

            if (rs.killAgent(tupla_agent_id, null, 0)){
                System.out.println("Agent "+tupla_agent_id+" removed from the simulation...");

                String postUrl = "http://"+host+":5000/api/v1/resources/model_to_router";// put in your url
                JSONObject json_obj = new JSONObject();
                json_obj.put("agent_id",tupla_agent_id);
                json_obj.put("data",tupla_data);
                json_obj.put("path",tupla_path);

                HttpClient httpClient = HttpClientBuilder.create().build();
                HttpPost post = new HttpPost(postUrl);
                StringEntity postingString = new StringEntity(json_obj.toString());//gson.tojson() converts your pojo to json
                post.setEntity(postingString);
                post.setHeader("Content-type", "application/json");
                HttpResponse  response = httpClient.execute(post);
            } else {
                System.out.println("Erro ao remover o agente da simulação...");
            }

        } catch (Exception e) {
            e.printStackTrace();
  
            // Prints what exception has been thrown
            System.out.println(e);
        }

        // everything ok, so returns true
        return true;
    }
}