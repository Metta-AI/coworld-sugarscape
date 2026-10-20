extensions [
  py
  ; ... your other extensions
]

turtles-own [
  sugar           ;; the amount of sugar this turtle has
  metabolism      ;; the amount of sugar that each turtles loses each tick
  vision          ;; the distance that this turtle can see in the horizontal and vertical directions
  vision-points   ;; the points that this turtle can see in relative to it's current position (based on vision)
  agent_id        ;; IDENTIFICAÇÃO DO AGENTE PARA O MIDDLEWARE
  historic        ;; HISTÓRICO DE VIAGEM DO AGENTE
]

patches-own [
  psugar           ;; the amount of sugar on this patch
  max-psugar       ;; the maximum amount of sugar that can be on this patch
]

globals [
  dead_agents
  config_file
  export_file
  qtd_received_agents
  qtd_received_agents_before
  qtd_sended_agents
]

;;
;; Setup Procedures
;;

to setup
  clear-all
  reset-ticks
  set config_file ""
  set export_file ""
  set dead_agents []
  ;;MODIFICATION;;
  ;;create-turtles initial-population [ turtle-setup ]
  new_request_to_register
  ;new_setup
  setup-patches
  set qtd_received_agents 0
  set qtd_received_agents_before 0
  set qtd_sended_agents 0
end

to new_setup
  load-config-from-file2
end

to new_request_to_register
  print("NL: funcao python new_request_to_register")
  print("NL: no netlogo, tempo inicial do request_to_register")
  print(date-and-time)
  py:setup py:python
  print("NL: iniciando register: ")
  py:run "from db_python_netlogo import request_to_register"
  let result py:runresult (word "request_to_register('" ("m2") "'" "," (400) ", " (800) ")")
  print("NL: retorno register: ")
  print(result)
  print("NL: no netlogo, tempo final do request_to_register")
  print(date-and-time)
end

to request_to_register
  let path2 "netlogo_output/request_new_agent.txt"
  file-open path2
  file-print (word "" 1 " " initial-population)
  file-close
;  if (not (file-exists? "request_new_agent.txt"))
;  [
;    file-open path2
;    file-print (word "" 2 " " initial-population)
;    file-close
;
;    let deleted false
;
;    while [deleted = false]
;    [
;      carefully
;      [
;        file-delete "request_new_agent.txt"
;        print "file deleted"
;        set deleted true
;      ]
;      [
;        print error-message
;      ]
;    ]
;  ]
  ;print "---"
end

to new_send_agent_to_model
  print("NL: funcao python new_send_agent_to_model")
  py:setup py:python
  py:run "from db_python_netlogo import send_agent_to_router"
  ; "send_agent_to_router('12', '[1 2 3]', '1-1')"

  let updated_historic ""
  ifelse (historic = "")
  [
    set updated_historic 2
  ]
  [
    set updated_historic (word "" (historic) "-2")
  ]
  let tupla []
  set tupla lput sugar tupla
  set tupla lput metabolism tupla
  set tupla lput vision tupla

  print("NL: sending this agent to router:")
  print(agent_id)
  let result py:runresult (word "send_agent_to_router('" (agent_id) "', '" tupla "', '" (updated_historic) "')")

  print("NL: Envio de agente realizado com sucesso?")
  print (result)
;  print("NL: Todos os agentes para processar:")
;  print(result)
;  print("NL: separados:")
;  ifelse(length result > 0)
;  [
;    print("NL: entra primeiro if")
;    foreach result
;    [
;      x ->
;      print("NL: agente: ")
;      print (x)
;
;      print("NL: agent_id:")
;      print(item 0 x)
;      print("NL: tupla interna:")
;      print(item 1 x)
;      print("NL: path:")
;      print(item 2 x)
;
;      let tupla_interna read-from-string item 1 x
;
;      print("NL: tupla interna 0 - sugar:")
;      print(item 0 tupla_interna)
;      print("NL: tupla interna 1 - metabolism:")
;      print(item 1 tupla_interna)
;      print("NL: tupla interna 2 - vision:")
;      print(item 2 tupla_interna)
;
;      create-turtles 1
;      [
;        set agent_id item 0 x
;        ;set sugar item 2 line
;        set sugar item 0 tupla_interna
;        set metabolism item 1 tupla_interna
;        set vision item 2 tupla_interna
;        ;set historic word (item 5 line) "-2"
;        set historic item 2 x
;        print ("historic:")
;        print (historic)
;
;        set shape "circle"
;        move-to one-of patches with [not any? other turtles-here]
;        ;set sugar random-in-range 5 25
;        ;set metabolism random-in-range 1 4
;        ;set vision random-in-range 1 6
;        ;; turtles can look horizontally and vertically up to vision patches
;        ;; but cannot look diagonally at all
;        set vision-points []
;        foreach (range 1 (vision + 1)) [ n ->
;          set vision-points sentence vision-points (list (list 0 n) (list n 0) (list 0 (- n)) (list (- n) 0))
;        ]
;        run visualization
;        print "new agent created from previous model"
;      ]
;    ]
;  ]
;  [
;    print ("banco vazio")
;  ]
;  print("NL: fim receiving_agents: -----------")
end

to send_agent_to_model
  if (send_agents)
  [
    ;let path2 "netlogo_output/send_agent.txt"
    let path2 (word "netlogo_output/2/out" (agent_id) ".txt")
    file-open path2
    ;file-write (word "id:" random 3 ",action:" random 100)
    ;breed [test_agents test_agent]

    ;  foreach dead_agents
    ;  [
    ;    x -> file-write (word "" (x) "/" ("dead"))
    ;    ;file-write (word "a")
    ;  ]

    ifelse (historic = "")
    [
      file-print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) " " "2" "]")
    ]
    [
      file-print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) " " "\"" (word "" (historic) "-2") "\"" "]")
    ]

    ;file-print (word "[" "\"" "agent" "\"" " " (who) " " (sugar) " " (metabolism) " " (vision) " " "\"" (historic) "\"" "]")

    ;  ask turtles
    ;  [
    ;    file-print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) "]")
    ;    ;print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) "]")
    ;  ]
    file-close

    set path2 "netlogo_output/general_send_agent.txt"
    file-open path2
    ;file-write (word "id:" random 3 ",action:" random 100)
    ;breed [test_agents test_agent]

    ;  foreach dead_agents
    ;  [
    ;    x -> file-write (word "" (x) "/" ("dead"))
    ;    ;file-write (word "a")
    ;  ]

    ;file-print (word "[" "\"" "agent" "\"" " " (who) " " (sugar) " " (metabolism) " " (vision) "]")
    ;file-print (word "[" "\"" "agent" "\"" " " (who) " " (sugar) " " (metabolism) " " (vision) " " (historic) "]")

    ifelse (historic = "")
    [
      file-print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) " " ("2") "]")
    ]
    [
      file-print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) " " "\"" (word "" (historic) "-2") "\"" "]")
    ]

    set qtd_sended_agents (qtd_sended_agents + 1)

    ;  ask turtles
    ;  [
    ;    file-print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) "]")
    ;    ;print (word "[" "\"" "agent" "\"" " " (agent_id) " " (sugar) " " (metabolism) " " (vision) "]")
    ;  ]
    file-close
  ]
end

to new_check_new_agent
  print("NL: funcao python new_check_new_agent")
  print("NL: no netlogo, tempo inicial do new_check_new_agent")
  print(date-and-time)
  py:setup py:python
  py:run "from db_python_netlogo import receiving_agents"
  let result py:runresult (word "receiving_agents('" ("m2") "')")
  print("NL: receiving_agents: -----------")
  print("NL: Todos os agentes para processar:")
  print(result)
  print("NL: separados:")
  ifelse(length result > 0)
  [
    print("NL: entra primeiro if")
    foreach result
    [
      x ->
      print("NL: agente: ")
      print (x)

      print("NL: agent_id:")
      print(item 0 x)
      print("NL: tupla interna:")
      print(item 1 x)
      print("NL: path:")
      print(item 2 x)

      let tupla_interna read-from-string item 1 x

      print("NL: tupla interna 0 - sugar:")
      print(item 0 tupla_interna)
      print("NL: tupla interna 1 - metabolism:")
      print(item 1 tupla_interna)
      print("NL: tupla interna 2 - vision:")
      print(item 2 tupla_interna)

      create-turtles 1
      [
        set agent_id item 0 x
        ;set sugar item 0 tupla_interna
        ;TEMPORARIO
        set sugar random-in-range 5 25
        set metabolism item 1 tupla_interna
        set vision item 2 tupla_interna
        set historic item 2 x
        print ("historic:")
        print (historic)

        set shape "circle"
        move-to one-of patches with [not any? other turtles-here]
        ;set sugar random-in-range 5 25
        ;set metabolism random-in-range 1 4
        ;set vision random-in-range 1 6
        ;; turtles can look horizontally and vertically up to vision patches
        ;; but cannot look diagonally at all
        set vision-points []
        foreach (range 1 (vision + 1)) [ n ->
          set vision-points sentence vision-points (list (list 0 n) (list n 0) (list 0 (- n)) (list (- n) 0))
        ]
        run visualization
        print "new agent created from previous model"
      ]
    ]
  ]
  [
    print ("banco vazio")
  ]
  print("NL: no netlogo, tempo final do new_check_new_agent")
  print(date-and-time)
  print("NL: fim receiving_agents: -----------")
end

to testing_python
print("NL: funcao python testing_python")
  py:setup py:python
;  py:run "from db_python_netlogo import testing_send"
;  let result py:runresult (word "testing_send('" "[" "\"" "agent" "\"" " " ("agent_id") " " ("sugar") " " ("metabolism") " " ("vision") " " (word "\"" (ticks) "-1" "\"") "]" "')")
py:run "from db_python_netlogo import receiving_agents"
  let result py:runresult (word "receiving_agents('" ("m2") "')")
  print("NL: receiving_agents: -----------")
  print("NL: Todos os agentes para processar:")
  print(result)
  print("NL: separados:")
  ifelse(length result > 0)
  [
    print("NL: entra primeiro if")
    foreach result
    [
      x ->
      ;print("NL: 1")
      ;foreach read-from-string x
      print("NL: agente: ")
      print (x)

      ;let tupla read-from-string item 1 y
      print("NL: agent_id:")
      print(item 0 x)
      print("NL: tupla interna:")
      print(item 1 x)
      print("NL: path:")
      print(item 2 x)

      let tupla_interna read-from-string item 1 x

      print("NL: tupla interna 0 - sugar:")
      print(item 0 tupla_interna)
      print("NL: tupla interna 1 - metabolism:")
      print(item 1 tupla_interna)
      print("NL: tupla interna 2 - vision:")
      print(item 2 tupla_interna)
    ]
  ]
  [
    print ("banco vazio")
  ]
  print("NL: fim receiving_agents: -----------")

end

to check_new_agent
  file-close-all
  let original_file "netlogo_output/list_of_agents_2.txt"
  let to_delete []
  let files_to_check []
  if (file-exists? original_file)
  [
    ;print("NL: existe arquivo original")
    file-open original_file
    while [not file-at-end?]
    [
      let found_file file-read
      ;print("NL: linha encontrada:")
      ;print(found_file)
      set files_to_check lput found_file files_to_check
    ]
    file-close
  ]

  foreach files_to_check
  [
    x ->
;    print("NL: linhas do primeiro arquivo:")
;    print(x)

    if (file-exists? x)
    [
      print("NL: ---")
      print("NL: existe:")
      print(x)
      print("NL: ---")

      file-open x

      while [not file-at-end?]
      [
        let line file-read
        ifelse(item 0 line = "agent")
        [
          create-turtles 1
          [
            set agent_id item 1 line
            ;set sugar item 2 line
            set sugar 0
            set metabolism item 3 line
            set vision item 4 line
            ;set historic word (item 5 line) "-2"
            set historic item 5 line
            print ("historic:")
            print (historic)

            set shape "circle"
            move-to one-of patches with [not any? other turtles-here]
            ;set sugar random-in-range 5 25
            ;set metabolism random-in-range 1 4
            ;set vision random-in-range 1 6
            ;; turtles can look horizontally and vertically up to vision patches
            ;; but cannot look diagonally at all
            set vision-points []
            foreach (range 1 (vision + 1)) [ n ->
              set vision-points sentence vision-points (list (list 0 n) (list n 0) (list 0 (- n)) (list (- n) 0))
            ]
            run visualization
            print "new agent created from previous model"
          ]
          set to_delete lput x to_delete
          set qtd_received_agents_before (qtd_received_agents_before + 1)
        ]
        [
          print "string fora do padrão"
        ]
      ]
      file-close
    ]
  ]

  foreach to_delete
  [
    x ->
    print("NL: excluir:")
    print(x)
    file-delete x
  ]

;      if (file-exists? file_path)
;      [
;        print("NL: existe arquivo da linha")
;        file-open file_path
;        ;print "---"
;        while [not file-at-end?]
;        [
;          let line file-read
;          ifelse(item 0 line = "agent")
;          [
;            create-turtles 1
;            [
;              set agent_id item 1 line
;              ;set sugar item 2 line
;              set sugar 0
;              set metabolism item 3 line
;              set vision item 4 line
;              ;set historic word (item 5 line) "-2"
;              set historic item 5 line
;              print ("historic:")
;              print (historic)
;
;              set shape "circle"
;              move-to one-of patches with [not any? other turtles-here]
;              ;set sugar random-in-range 5 25
;              ;set metabolism random-in-range 1 4
;              ;set vision random-in-range 1 6
;              ;; turtles can look horizontally and vertically up to vision patches
;              ;; but cannot look diagonally at all
;              set vision-points []
;              foreach (range 1 (vision + 1)) [ n ->
;                set vision-points sentence vision-points (list (list 0 n) (list n 0) (list 0 (- n)) (list (- n) 0))
;              ]
;              run visualization
;              print "new agent created from previous model"
;            ]
;            set to_delete lput file_path to_delete
;            set qtd_received_agents_before (qtd_received_agents_before + 1)
;          ]
;          [
;            print "eee"
;          ]
;        ]
;        file-close
;;        file-close
;;        print("NL: excluindo arquivo")
;;        print(file_path)
;;        file-delete file_path
;      ]
;    ]
;  file-close
;  ]
;
;  foreach to_delete
;  [
;    x ->
;    print("NL: excluir:")
;    print(x)
;    ;file-write (word "a")
;  ]
;  file-close-all
;  let original_file "netlogo_output/list_of_agents.txt"
;  let to_delete []
;  if (file-exists? original_file)
;  [
;    print("NL: existe arquivo original")
;    file-open original_file
;    while [not file-at-end?]
;    [
;      let file_path file-read
;      print("NL: linha encontrada:")
;      print(file_path)
;      if (file-exists? file_path)
;      [
;        print("NL: existe arquivo da linha")
;        file-open file_path
;        ;print "---"
;        while [not file-at-end?]
;        [
;          let line file-read
;          ifelse(item 0 line = "agent")
;          [
;            create-turtles 1
;            [
;              set agent_id item 1 line
;              ;set sugar item 2 line
;              set sugar 0
;              set metabolism item 3 line
;              set vision item 4 line
;              ;set historic word (item 5 line) "-2"
;              set historic item 5 line
;              print ("historic:")
;              print (historic)
;
;              set shape "circle"
;              move-to one-of patches with [not any? other turtles-here]
;              ;set sugar random-in-range 5 25
;              ;set metabolism random-in-range 1 4
;              ;set vision random-in-range 1 6
;              ;; turtles can look horizontally and vertically up to vision patches
;              ;; but cannot look diagonally at all
;              set vision-points []
;              foreach (range 1 (vision + 1)) [ n ->
;                set vision-points sentence vision-points (list (list 0 n) (list n 0) (list 0 (- n)) (list (- n) 0))
;              ]
;              run visualization
;              print "new agent created from previous model"
;            ]
;            set to_delete lput file_path to_delete
;            set qtd_received_agents_before (qtd_received_agents_before + 1)
;          ]
;          [
;            print "eee"
;          ]
;        ]
;        file-close
;;        file-close
;;        print("NL: excluindo arquivo")
;;        print(file_path)
;;        file-delete file_path
;      ]
;    ]
;  file-close
;  ]
;
;  foreach to_delete
;  [
;    x ->
;    print("NL: excluir:")
;    print(x)
;    ;file-write (word "a")
;  ]
end


to print_alive_agents
  let file_path "netlogo_output/m2_alive.txt"
  file-open file_path
  let alive_agents ""
  foreach sort-on [agent_id] turtles
  [
    the-turtle -> ask the-turtle
    [
      print agent_id
      file-write (agent_id)
      ifelse(alive_agents != "")
      [
        set alive_agents (word alive_agents "," agent_id)
      ]
      [
        set alive_agents (word alive_agents agent_id)
      ]
    ]
  ]

  if(alive_agents != "")
  [

    print("NL: funcao python send_agent_to_alive")
    py:setup py:python
    py:run "from db_python_netlogo import send_agent_to_alive"

    ;let model "m2"
    let result py:runresult (word "send_agent_to_alive('" (alive_agents) "', 'm2')")
    print("NL: Envio de agente realizado com sucesso?")
    print (result)
  ]
  file-close
end

to print_alive_agents_single
  let file_path "netlogo_output/m2_alive.txt"
  file-open file_path
  foreach sort-on [agent_id] turtles
  [
    the-turtle -> ask the-turtle
    [
      print agent_id
      file-write (agent_id)

      print("NL: funcao python send_agent_to_alive")
      py:setup py:python
      py:run "from db_python_netlogo import send_agent_to_alive"

      ;let model "m2"
      let result py:runresult (word "send_agent_to_alive('" (agent_id) "', 'm2')")
      print("NL: Envio de agente realizado com sucesso?")
      print (result)
    ]
  ]
  file-close
end

to load-config-from-file2
  file-open "netlogo_output/input_file.txt"
  while [not file-at-end?]
  [
    let line file-read
    ;show item 1 line
;    let item0 item 0 line
;    let item1 item 1 line
;    let item2 item 2 line
;    let item3 item 3 line
;    let item4 item 4 line

;    print item0
;    print item1
;    print item2

;    if(item0 = "num_agents")
;    [
;      set num_agents item1
;      create-test_agents num_agents
;      [
;        print who + 1
;      ]
;    ]

    ifelse(item 0 line = "agent")
    [
      create-turtles 1
      [
        set agent_id item 1 line
        set sugar item 2 line
        set metabolism item 3 line
        set vision item 4 line

        set color red
        set shape "circle"
        move-to one-of patches with [not any? other turtles-here]
        ;set sugar random-in-range 5 25
        ;set metabolism random-in-range 1 4
        ;set vision random-in-range 1 6
        ;; turtles can look horizontally and vertically up to vision patches
        ;; but cannot look diagonally at all
        set vision-points []
        foreach (range 1 (vision + 1)) [ n ->
          set vision-points sentence vision-points (list (list 0 n) (list n 0) (list 0 (- n)) (list (- n) 0))
        ]
        run visualization
      ]
    ]
    [
      ifelse(item 0 line = "config_file")
      [
        set config_file item 1 line
      ]
      [
        if(item 0 line = "export_file")
        [
          set config_file item 1 line
        ]
      ]
    ]
  ]
  file-close
end

to export_output_to_File
  print("NL: ---------- FIM DA SIMULACAO...")
;  print("NL: AGENTES QUE ENTRARIAM NA SIMULACAO: ")
;  py:setup py:python
;  py:run "from db_python_netlogo import receiving_agents"
;  let result py:runresult (word "receiving_agents('" ("m2") "')")
;  ifelse(length result > 0)
;  [
;    print("NL: entra primeiro if")
;    foreach result
;    [
;      x ->
;
;      ;print("NL: agent_id:")
;      print(item 0 x)
;    ]
;  ]
;  [
;    print("NL: Nenhum agente para entrar na simulacao")
;  ]

  print("NL: AGENTES VIVOS: ")
  print_alive_agents
;  export-output "netlogo_output/m2.txt"
  print("NL: ---------- FIM!")
end

to print_agent_random
  let path2 "netlogo_output/output_file.txt"
  file-open path2
  ;file-write (word "id:" random 3 ",action:" random 100)
  ;breed [test_agents test_agent]

  foreach dead_agents
  [
    x -> file-write (word "" (x) "/" ("dead"))
    ;file-write (word "a")
  ]

  ask turtles
  [
;    print (who + 1)
;    file-write (word "" (who + 1) "/" random 100)
    ;print (who + 1)
    file-write (word "" (agent_id) "/" ("alive"))
  ]
  file-close
end

to turtle-setup ;; turtle procedure
  set historic ""
  set color red
  set shape "circle"
  move-to one-of patches with [not any? other turtles-here]
  set sugar random-in-range 5 25
  set metabolism random-in-range 1 4
  set vision random-in-range 1 6
  ;; turtles can look horizontally and vertically up to vision patches
  ;; but cannot look diagonally at all
  set vision-points []
  foreach (range 1 (vision + 1)) [ n ->
    set vision-points sentence vision-points (list (list 0 n) (list n 0) (list 0 (- n)) (list (- n) 0))
  ]
  run visualization
end

to setup-patches
  file-open "sugar-map.txt"
  foreach sort patches [ p ->
    ask p [
      set max-psugar file-read
      set psugar max-psugar
      patch-recolor
    ]
  ]
  file-close
end

;;
;; Runtime Procedures
;;

to go
  print("NL: ------------BEGIN TICK --------------")
  print("NL: Tick number: ")
  print(ticks)
;  if (ticks = 1000)
;  [
;    stop
;  ]
;testing_python

  if (ticks = 1)
  [
    ;send_agent_to_model
  ]

  new_check_new_agent


;  if not any? turtles [
;    stop
;  ]
  ask patches [
    patch-growback
    patch-recolor
  ]
  ask turtles [
    turtle-move
    turtle-eat
    if sugar <= 0
    [
      set dead_agents lput agent_id dead_agents
      new_send_agent_to_model
      ;print "agent died, sending to other model"
      die
    ]
    run visualization
  ]
  print("NL: ------------END TICK --------------")
  tick
end

to turtle-move ;; turtle procedure
  ;; consider moving to unoccupied patches in our vision, as well as staying at the current patch
  let move-candidates (patch-set patch-here (patches at-points vision-points) with [not any? turtles-here])
  let possible-winners move-candidates with-max [psugar]
  if any? possible-winners [
    ;; if there are any such patches move to one of the patches that is closest
    move-to min-one-of possible-winners [distance myself]
  ]
end

to turtle-eat ;; turtle procedure
  ;; metabolize some sugar, and eat all the sugar on the current patch
  set sugar (sugar - metabolism + psugar)
  set psugar 0
end

to patch-recolor ;; patch procedure
  ;; color patches based on the amount of sugar they have
  set pcolor (yellow + 4.9 - psugar)
end

to patch-growback ;; patch procedure
  ;; gradually grow back all of the sugar for the patch
  set psugar min (list max-psugar (psugar + 1))
end

;;
;; Utilities
;;

to-report random-in-range [low high]
  report low + random (high - low + 1)
end

;;
;; Visualization Procedures
;;

to no-visualization ;; turtle procedure
  set color red
end

to color-agents-by-vision ;; turtle procedure
  set color red - (vision - 3.5)
end

to color-agents-by-metabolism ;; turtle procedure
  set color red + (metabolism - 2.5)
end


; Copyright 2009 Uri Wilensky.
; See Info tab for full copyright and license.
@#$#@#$#@
GRAPHICS-WINDOW
300
10
708
419
-1
-1
8.0
1
10
1
1
1
0
1
1
1
0
49
0
49
1
1
1
ticks
30.0

BUTTON
10
55
90
95
NIL
setup
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

BUTTON
100
55
190
95
NIL
go
T
1
T
OBSERVER
NIL
NIL
NIL
NIL
0

BUTTON
200
55
290
95
go once
go
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
0

CHOOSER
10
105
290
150
visualization
visualization
"no-visualization" "color-agents-by-vision" "color-agents-by-metabolism"
0

PLOT
720
10
940
165
Population
NIL
NIL
0.0
10.0
0.0
10.0
true
false
"" ""
PENS
"default" 1.0 0 -16777216 true "" "plotxy ticks count turtles"

PLOT
950
10
1170
165
Wealth distribution
NIL
NIL
0.0
10.0
0.0
10.0
true
false
"" ""
PENS
"default" 1.0 1 -16777216 true "" "set-histogram-num-bars 10\nset-plot-x-range 0 (max [sugar] of turtles + 1)\nset-plot-pen-interval (max [sugar] of turtles + 1) / 10\nhistogram [sugar] of turtles"

SLIDER
10
15
290
48
initial-population
initial-population
10
1000
400.0
10
1
NIL
HORIZONTAL

PLOT
720
175
940
330
Average vision
NIL
NIL
0.0
10.0
0.0
6.0
true
false
"" ""
PENS
"default" 1.0 0 -16777216 true "" "plotxy ticks mean [vision] of turtles"

PLOT
950
175
1170
330
Average metabolism
NIL
NIL
0.0
10.0
0.0
5.0
true
false
"" ""
PENS
"default" 1.0 0 -16777216 true "" "plotxy ticks mean [metabolism] of turtles"

MONITOR
95
160
190
209
population
count turtles
17
1
12

BUTTON
155
305
297
338
NIL
print_agent_random
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

BUTTON
165
225
297
258
NIL
check_new_agent
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

BUTTON
5
230
157
263
NIL
send_agent_to_model
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

BUTTON
20
300
137
333
NIL
request_to_register
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

BUTTON
155
370
287
403
NIL
print_alive_agents
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

SWITCH
15
370
142
403
send_agents
send_agents
0
1
-1000

BUTTON
205
445
332
478
NIL
testing_python
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

@#$#@#$#@
## WHAT IS IT?

This second model in the NetLogo Sugarscape suite implements Epstein & Axtell's Sugarscape Constant Growback model, as described in chapter 2 of their book Growing Artificial Societies: Social Science from the Bottom Up. It simulates a population with limited, spatially-distributed resources available. It differs from Sugarscape 1 Immediate Growback in that the growback of sugar is gradual rather than instantaneous.

## HOW IT WORKS

Each patch contains some sugar, the maximum amount of which is predetermined. At each tick, each patch regains one unit of sugar, until it reaches the maximum amount. The amount of sugar a patch currently contains is indicated by its color; the darker the yellow, the more sugar.

At setup, agents are placed at random within the world. Each agent can only see a certain distance horizontally and vertically. At each tick, each agent will move to the nearest unoccupied location within their vision range with the most sugar, and collect all the sugar there.  If its current location has as much or more sugar than any unoccupied location it can see, it will stay put.

Agents also use (and thus lose) a certain amount of sugar each tick, based on their metabolism rates. If an agent runs out of sugar, it dies.

## HOW TO USE IT

Set the INITIAL-POPULATION slider before pressing SETUP. This determines the number of agents in the world.

Press SETUP to populate the world with agents and import the sugar map data. GO will run the simulation continuously, while GO ONCE will run one tick.

The VISUALIZATION chooser gives different visualization options and may be changed while the GO button is pressed. When NO-VISUALIZATION is selected all the agents will be red. When COLOR-AGENTS-BY-VISION is selected the agents with the longest vision will be darkest and, similarly, when COLOR-AGENTS-BY-METABOLISM is selected the agents with the lowest metabolism will be darkest.

The four plots show the world population over time, the distribution of sugar among the agents, the mean vision of all surviving agents over time, and the mean metabolism of all surviving agents over time.

## THINGS TO NOTICE

The world has a carrying capacity, which is lower than the initial population of the world. Agents who are born in sugarless places or who consume more sugar than the land cannot be supported by the world, and die. Other agents die from competition - although some places in the world have enough sugar to support them, the sugar supply is limited and other agents may reach and consume it first.

As the population stabilizes, the average vision increases while the average metabolism decreases. Agents with lower vision cannot find the better sugar patches, while agents with high metabolism cannot support themselves. The death of these agents causes the attribute averages to change.

## THINGS TO TRY

How dependent is the carrying capacity on the initial population size?  Is there a direct relationship?

## EXTENDING THE MODEL

How does changing the amount or rate of sugar growback affect the behavior of the model?

## NETLOGO FEATURES

All of the Sugarscape models create the world by using `file-read` to import data from an external file, `sugar-map.txt`. This file defines both the initial and the maximum sugar value for each patch in the world.

Since agents cannot see diagonally we cannot use `in-radius` to find the patches in the agents' vision.  Instead, we use `at-points`.

## RELATED MODELS

Other models in the NetLogo Sugarscape suite include:

* Sugarscape 1 Immediate Growback
* Sugarscape 3 Wealth Distribution

## CREDITS AND REFERENCES

Epstein, J. and Axtell, R. (1996). Growing Artificial Societies: Social Science from the Bottom Up.  Washington, D.C.: Brookings Institution Press.

## HOW TO CITE

If you mention this model or the NetLogo software in a publication, we ask that you include the citations below.

For the model itself:

* Li, J. and Wilensky, U. (2009).  NetLogo Sugarscape 2 Constant Growback model.  http://ccl.northwestern.edu/netlogo/models/Sugarscape2ConstantGrowback.  Center for Connected Learning and Computer-Based Modeling, Northwestern University, Evanston, IL.

Please cite the NetLogo software as:

* Wilensky, U. (1999). NetLogo. http://ccl.northwestern.edu/netlogo/. Center for Connected Learning and Computer-Based Modeling, Northwestern University, Evanston, IL.

## COPYRIGHT AND LICENSE

Copyright 2009 Uri Wilensky.

![CC BY-NC-SA 3.0](http://ccl.northwestern.edu/images/creativecommons/byncsa.png)

This work is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 3.0 License.  To view a copy of this license, visit https://creativecommons.org/licenses/by-nc-sa/3.0/ or send a letter to Creative Commons, 559 Nathan Abbott Way, Stanford, California 94305, USA.

Commercial licenses are also available. To inquire about commercial licenses, please contact Uri Wilensky at uri@northwestern.edu.

<!-- 2009 Cite: Li, J. -->
@#$#@#$#@
default
true
0
Polygon -7500403 true true 150 5 40 250 150 205 260 250

airplane
true
0
Polygon -7500403 true true 150 0 135 15 120 60 120 105 15 165 15 195 120 180 135 240 105 270 120 285 150 270 180 285 210 270 165 240 180 180 285 195 285 165 180 105 180 60 165 15

arrow
true
0
Polygon -7500403 true true 150 0 0 150 105 150 105 293 195 293 195 150 300 150

box
false
0
Polygon -7500403 true true 150 285 285 225 285 75 150 135
Polygon -7500403 true true 150 135 15 75 150 15 285 75
Polygon -7500403 true true 15 75 15 225 150 285 150 135
Line -16777216 false 150 285 150 135
Line -16777216 false 150 135 15 75
Line -16777216 false 150 135 285 75

bug
true
0
Circle -7500403 true true 96 182 108
Circle -7500403 true true 110 127 80
Circle -7500403 true true 110 75 80
Line -7500403 true 150 100 80 30
Line -7500403 true 150 100 220 30

butterfly
true
0
Polygon -7500403 true true 150 165 209 199 225 225 225 255 195 270 165 255 150 240
Polygon -7500403 true true 150 165 89 198 75 225 75 255 105 270 135 255 150 240
Polygon -7500403 true true 139 148 100 105 55 90 25 90 10 105 10 135 25 180 40 195 85 194 139 163
Polygon -7500403 true true 162 150 200 105 245 90 275 90 290 105 290 135 275 180 260 195 215 195 162 165
Polygon -16777216 true false 150 255 135 225 120 150 135 120 150 105 165 120 180 150 165 225
Circle -16777216 true false 135 90 30
Line -16777216 false 150 105 195 60
Line -16777216 false 150 105 105 60

car
false
0
Polygon -7500403 true true 300 180 279 164 261 144 240 135 226 132 213 106 203 84 185 63 159 50 135 50 75 60 0 150 0 165 0 225 300 225 300 180
Circle -16777216 true false 180 180 90
Circle -16777216 true false 30 180 90
Polygon -16777216 true false 162 80 132 78 134 135 209 135 194 105 189 96 180 89
Circle -7500403 true true 47 195 58
Circle -7500403 true true 195 195 58

circle
false
0
Circle -7500403 true true 0 0 300

circle 2
false
0
Circle -7500403 true true 0 0 300
Circle -16777216 true false 30 30 240

cow
false
0
Polygon -7500403 true true 200 193 197 249 179 249 177 196 166 187 140 189 93 191 78 179 72 211 49 209 48 181 37 149 25 120 25 89 45 72 103 84 179 75 198 76 252 64 272 81 293 103 285 121 255 121 242 118 224 167
Polygon -7500403 true true 73 210 86 251 62 249 48 208
Polygon -7500403 true true 25 114 16 195 9 204 23 213 25 200 39 123

cylinder
false
0
Circle -7500403 true true 0 0 300

dot
false
0
Circle -7500403 true true 90 90 120

face happy
false
0
Circle -7500403 true true 8 8 285
Circle -16777216 true false 60 75 60
Circle -16777216 true false 180 75 60
Polygon -16777216 true false 150 255 90 239 62 213 47 191 67 179 90 203 109 218 150 225 192 218 210 203 227 181 251 194 236 217 212 240

face neutral
false
0
Circle -7500403 true true 8 7 285
Circle -16777216 true false 60 75 60
Circle -16777216 true false 180 75 60
Rectangle -16777216 true false 60 195 240 225

face sad
false
0
Circle -7500403 true true 8 8 285
Circle -16777216 true false 60 75 60
Circle -16777216 true false 180 75 60
Polygon -16777216 true false 150 168 90 184 62 210 47 232 67 244 90 220 109 205 150 198 192 205 210 220 227 242 251 229 236 206 212 183

fish
false
0
Polygon -1 true false 44 131 21 87 15 86 0 120 15 150 0 180 13 214 20 212 45 166
Polygon -1 true false 135 195 119 235 95 218 76 210 46 204 60 165
Polygon -1 true false 75 45 83 77 71 103 86 114 166 78 135 60
Polygon -7500403 true true 30 136 151 77 226 81 280 119 292 146 292 160 287 170 270 195 195 210 151 212 30 166
Circle -16777216 true false 215 106 30

flag
false
0
Rectangle -7500403 true true 60 15 75 300
Polygon -7500403 true true 90 150 270 90 90 30
Line -7500403 true 75 135 90 135
Line -7500403 true 75 45 90 45

flower
false
0
Polygon -10899396 true false 135 120 165 165 180 210 180 240 150 300 165 300 195 240 195 195 165 135
Circle -7500403 true true 85 132 38
Circle -7500403 true true 130 147 38
Circle -7500403 true true 192 85 38
Circle -7500403 true true 85 40 38
Circle -7500403 true true 177 40 38
Circle -7500403 true true 177 132 38
Circle -7500403 true true 70 85 38
Circle -7500403 true true 130 25 38
Circle -7500403 true true 96 51 108
Circle -16777216 true false 113 68 74
Polygon -10899396 true false 189 233 219 188 249 173 279 188 234 218
Polygon -10899396 true false 180 255 150 210 105 210 75 240 135 240

house
false
0
Rectangle -7500403 true true 45 120 255 285
Rectangle -16777216 true false 120 210 180 285
Polygon -7500403 true true 15 120 150 15 285 120
Line -16777216 false 30 120 270 120

leaf
false
0
Polygon -7500403 true true 150 210 135 195 120 210 60 210 30 195 60 180 60 165 15 135 30 120 15 105 40 104 45 90 60 90 90 105 105 120 120 120 105 60 120 60 135 30 150 15 165 30 180 60 195 60 180 120 195 120 210 105 240 90 255 90 263 104 285 105 270 120 285 135 240 165 240 180 270 195 240 210 180 210 165 195
Polygon -7500403 true true 135 195 135 240 120 255 105 255 105 285 135 285 165 240 165 195

line
true
0
Line -7500403 true 150 0 150 300

line half
true
0
Line -7500403 true 150 0 150 150

pentagon
false
0
Polygon -7500403 true true 150 15 15 120 60 285 240 285 285 120

person
false
0
Circle -7500403 true true 110 5 80
Polygon -7500403 true true 105 90 120 195 90 285 105 300 135 300 150 225 165 300 195 300 210 285 180 195 195 90
Rectangle -7500403 true true 127 79 172 94
Polygon -7500403 true true 195 90 240 150 225 180 165 105
Polygon -7500403 true true 105 90 60 150 75 180 135 105

plant
false
0
Rectangle -7500403 true true 135 90 165 300
Polygon -7500403 true true 135 255 90 210 45 195 75 255 135 285
Polygon -7500403 true true 165 255 210 210 255 195 225 255 165 285
Polygon -7500403 true true 135 180 90 135 45 120 75 180 135 210
Polygon -7500403 true true 165 180 165 210 225 180 255 120 210 135
Polygon -7500403 true true 135 105 90 60 45 45 75 105 135 135
Polygon -7500403 true true 165 105 165 135 225 105 255 45 210 60
Polygon -7500403 true true 135 90 120 45 150 15 180 45 165 90

square
false
0
Rectangle -7500403 true true 30 30 270 270

square 2
false
0
Rectangle -7500403 true true 30 30 270 270
Rectangle -16777216 true false 60 60 240 240

star
false
0
Polygon -7500403 true true 151 1 185 108 298 108 207 175 242 282 151 216 59 282 94 175 3 108 116 108

target
false
0
Circle -7500403 true true 0 0 300
Circle -16777216 true false 30 30 240
Circle -7500403 true true 60 60 180
Circle -16777216 true false 90 90 120
Circle -7500403 true true 120 120 60

tree
false
0
Circle -7500403 true true 118 3 94
Rectangle -6459832 true false 120 195 180 300
Circle -7500403 true true 65 21 108
Circle -7500403 true true 116 41 127
Circle -7500403 true true 45 90 120
Circle -7500403 true true 104 74 152

triangle
false
0
Polygon -7500403 true true 150 30 15 255 285 255

triangle 2
false
0
Polygon -7500403 true true 150 30 15 255 285 255
Polygon -16777216 true false 151 99 225 223 75 224

truck
false
0
Rectangle -7500403 true true 4 45 195 187
Polygon -7500403 true true 296 193 296 150 259 134 244 104 208 104 207 194
Rectangle -1 true false 195 60 195 105
Polygon -16777216 true false 238 112 252 141 219 141 218 112
Circle -16777216 true false 234 174 42
Rectangle -7500403 true true 181 185 214 194
Circle -16777216 true false 144 174 42
Circle -16777216 true false 24 174 42
Circle -7500403 false true 24 174 42
Circle -7500403 false true 144 174 42
Circle -7500403 false true 234 174 42

turtle
true
0
Polygon -10899396 true false 215 204 240 233 246 254 228 266 215 252 193 210
Polygon -10899396 true false 195 90 225 75 245 75 260 89 269 108 261 124 240 105 225 105 210 105
Polygon -10899396 true false 105 90 75 75 55 75 40 89 31 108 39 124 60 105 75 105 90 105
Polygon -10899396 true false 132 85 134 64 107 51 108 17 150 2 192 18 192 52 169 65 172 87
Polygon -10899396 true false 85 204 60 233 54 254 72 266 85 252 107 210
Polygon -7500403 true true 119 75 179 75 209 101 224 135 220 225 175 261 128 261 81 224 74 135 88 99

wheel
false
0
Circle -7500403 true true 3 3 294
Circle -16777216 true false 30 30 240
Line -7500403 true 150 285 150 15
Line -7500403 true 15 150 285 150
Circle -7500403 true true 120 120 60
Line -7500403 true 216 40 79 269
Line -7500403 true 40 84 269 221
Line -7500403 true 40 216 269 79
Line -7500403 true 84 40 221 269

x
false
0
Polygon -7500403 true true 270 75 225 30 30 225 75 270
Polygon -7500403 true true 30 75 75 30 270 225 225 270
@#$#@#$#@
NetLogo 6.0.4
@#$#@#$#@
@#$#@#$#@
@#$#@#$#@
<experiments>
  <experiment name="experiment1" repetitions="1" runMetricsEveryStep="true">
    <setup>setup</setup>
    <go>go</go>
    <final>export_output_to_File</final>
    <timeLimit steps="1000"/>
    <metric>count turtles</metric>
    <enumeratedValueSet variable="visualization">
      <value value="&quot;no-visualization&quot;"/>
    </enumeratedValueSet>
    <enumeratedValueSet variable="initial-population">
      <value value="400"/>
    </enumeratedValueSet>
  </experiment>
</experiments>
@#$#@#$#@
@#$#@#$#@
default
0.0
-0.2 0 0.0 1.0
0.0 1 1.0 0.0
0.2 0 0.0 1.0
link direction
true
0
Line -7500403 true 150 150 90 180
Line -7500403 true 150 150 210 180
@#$#@#$#@
1
@#$#@#$#@
