!initial_print.
@pfunction3[atomic]
+!initial_print : true
<-
	/* .print("Hello there. I'm a checker agent"); */
	/* .print("Checking and creating agent if it exists on file"); */
	mylib.my_create_ag;
	.wait(1000);
	!initial_print.