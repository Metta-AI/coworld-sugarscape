/* price(Task,X) :- .random(R) & X = (10*R)+100. */



initial.
+initial : true
<- 
	.print("Hello there. I'm a regular agent");
	?agent_id(AGENTID);
	?path(PATH);
	
	/* Algo que é carregado entre as simulações */	
	.random(R);
	+my_testing(R);
	?my_testing(R);
	.print("R: ", R);

	.abolish(agent_id(_));
	.abolish(path(_));

	?sugar(SUGAR);
	?metabolism(METABOLISM);
	?vision(VISION);

	.print("Sugar ", SUGAR);
	.print("Metabolism ", METABOLISM);
	.print("Vision ", VISION);
	
	.abolish(sugar(_));
	.abolish(metabolism(_));
	.abolish(vision(_));

	.my_name(MYNAME);
	.concat("src/agt/list/",MYNAME,".asl",NAME)
	/* É possível salvar o agente já adicionando crenças, como o exemplo do say(hello) */	
	.save_agent(NAME,[start,say(hello)]);
	.print("Saved my information on file. Sending message to remove agent from simulation");

	.send(killer_agent, tell, kill(AGENTID, PATH, MYNAME, SUGAR, METABOLISM, VISION));
	.send(killer_agent, untell, kill(AGENTID, PATH, MYNAME, SUGAR, METABOLISM, VISION)).

/*
initial_print1.
+initial_print1 : true
<- 
	.print("Hello there. I'm a saver agent");

	?agent_id(V0);
	?path(V1);



	
	/* Algo que é carregado entre as simulações */
	
	.random(R);

	+my_testing(R);

	?my_testing(R);

	.print("R: ", R);
	





	.abolish(agent_id(_));
	.abolish(path(_));

	?sugar(B0);
	?metabolism(B1);
	?vision(B2);

	.print("Sugar ", B0);
	.print("Metabolism ", B1);
	.print("Vision ", B2);

	
	.abolish(sugar(_));
	.abolish(metabolism(_));
	.abolish(vision(_));


	.my_name(X);
	.concat("src/agt/list/",X,".asl",NAME)
	.save_agent(NAME,[start,say(hello)]);
	.print("Saved my information on file. Sending message to remove agent from simulation");

	.send(killer_agent, tell, kill(V0, V1, X, B0, B1, B2));
	.send(killer_agent, untell, kill(V0, V1, X, B0, B1, B2)).
*/



initial_print4.
+initial_print5 : true
<- 
	.print("Hello there. I'm a saver agent");

	?agent_id(V0);
	?path(V1);



	/*
	.random(R);

	+my_testing(R);

	?my_testing(R);

	.print("R: ", R);
	*/

	



	.abolish(agent_id(_));
	.abolish(path(_));

	?sugar(B0);
	?metabolism(B1);
	?vision(B2);

	.print("Sugar ", B0);
	.print("Metabolism ", B1);
	.print("Vision ", B2);

	
	.abolish(sugar(_));
	.abolish(metabolism(_));
	.abolish(vision(_));

	NewA = B0 + 1
	NewB = B1 + 1
	NewC = B2 + 1

	.print("Sugar after", NewA);
	.print("Metabolism after", NewB);
	.print("Vision after", NewC);


	+sugar(NewA);
	+metabolism(NewB);
	+vision(NewC);

	?sugar(A);
	?metabolism(B);
	?vision(C);

	.print("Sugar ", A);
	.print("Metabolism ", B);
	.print("Vision ", C);


	.my_name(X);
	.concat("src/agt/list/",X,".asl",NAME)
	.save_agent(NAME,[start,say(hello)]);
	.print("Saved my information on file. Sending message to remove agent from simulation").

	/*
	.send(killer_agent, tell, kill(V0, V1, X, B0, B1, B2));
	.send(killer_agent, untell, kill(V0, V1, X, B0, B1, B2)).

	*/

initial_print6.
+initial_print7 : true
<- 
	.print("Hello there. I'm a saver agent");

	?agent_id(V0);
	?path(V1);



	/*
	.random(R);

	+my_testing(R);

	?my_testing(R);

	.print("R: ", R);
	*/





	.abolish(agent_id(_));
	.abolish(path(_));

	?sugar(B0);
	?metabolism(B1);
	?vision(B2);

	.print("Sugar ", B0);
	.print("Metabolism ", B1);
	.print("Vision ", B2);

	
	.abolish(sugar(_));
	.abolish(metabolism(_));
	.abolish(vision(_));


	.my_name(X);
	.concat("src/agt/list/",X,".asl",NAME)
	.save_agent(NAME,[start,say(hello)]);
	.print("Saved my information on file. Sending message to remove agent from simulation").

	/*
	.send(killer_agent, tell, kill(V0, V1, X, B0, B1, B2));
	.send(killer_agent, untell, kill(V0, V1, X, B0, B1, B2)).

	*/