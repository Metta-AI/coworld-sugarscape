initial_print.
+initial_print : true
  <- .print("I'm a killer agent").

@pfunction4[atomic]
+kill(AGENTID, PATH, MYNAME, SUGAR, METABOLISM, VISION) : true
  <- .print("I've received a message to kill agent ",AGENTID);
     .print("Killing agent ",AGENTID);
     mylib.my_delete_ag(AGENTID, PATH, MYNAME, SUGAR, METABOLISM, VISION);
     .wait(2000);
     +killed_agent(AGENTID);
     .print("This agent has being removed from the simulation: ",AGENTID).