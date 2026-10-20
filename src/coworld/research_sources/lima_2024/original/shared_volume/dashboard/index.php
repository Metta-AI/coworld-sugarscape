<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-EVSTQN3/azprG1Anm3QDgpJLIm9Nao0Yz1ztcQTwFspd3yD65VohhpuuCOmLASjC" crossorigin="anonymous">

<link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.10.25/css/jquery.dataTables.min.css">

<script type="text/javascript" language="javascript" src="https://code.jquery.com/jquery-3.5.1.js"></script>

<script type="text/javascript" language="javascript" src="https://cdn.datatables.net/1.10.25/js/jquery.dataTables.min.js"></script>


<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<center><h1>List of agents: m1</h1></center>
<table id="example1" class="display" style="width:100%">
<thead>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</thead>
<tbody>

<?php
$out = array();
foreach (glob('../jacamo/jacamo_model/src/agt/list/*.asl') as $filename) {
  $p = pathinfo($filename);
  $out[] = $p['filename'];
}

ini_set('display_errors', '1');
ini_set('display_startup_errors', '1');
error_reporting(E_ALL);

// Method: POST, PUT, GET etc
// Data: array("param" => "value") ==> index.php?param=value

function CallAPI($method, $url, $data = false)
{
  $curl = curl_init();

  switch ($method)
  {
    case "POST":
    curl_setopt($curl, CURLOPT_POST, 1);

    if ($data)
      curl_setopt($curl, CURLOPT_POSTFIELDS, $data);
    break;
    case "PUT":
    curl_setopt($curl, CURLOPT_PUT, 1);
    break;
    default:
    if ($data)
      $url = sprintf("%s?%s", $url, http_build_query($data));
  }

  // Optional Authentication:
  // curl_setopt($curl, CURLOPT_HTTPAUTH, CURLAUTH_BASIC);
  // curl_setopt($curl, CURLOPT_USERPWD, "username:password");

  curl_setopt($curl, CURLOPT_URL, $url);
  curl_setopt($curl, CURLOPT_RETURNTRANSFER, 1);

  $result = curl_exec($curl);

  curl_close($curl);

  return $result;
}

$host = getenv("host");
$response = CallAPI("GET", "http://".$host.":5000/api/v1/resources/output_php?model=m1");
$response = json_decode($response);

foreach ($response as $value) {
  echo "<tr>";
  $agent_id = $value[0];
  $data = str_replace("[", "", $value[1]);
  $data = str_replace("]", "", $data);
  $data = explode(" ", $data);
  $sugar = $data[0];
  $metabolism = $data[1];
  $vision = $data[2];
  $path = $value[2];
  $processed = $value[3];
  echo '<td class="ids">'.$agent_id.'</td>';
  echo '<td>'.$sugar.'</td>';
  echo '<td>'.$metabolism.'</td>';
  echo '<td class="vision">'.$vision.'</td>';
  echo '<td>'.$processed.'</td>';
  if (in_array(($agent_id), $out)) {
    echo '<td>'."<button value='".$agent_id."' class='btnSubmit buttonSubmit' type='button'>".$agent_id."</button>".'</td>';
  }
  else
    echo '<td><button>'."No File".'</button></td>';

  echo '<td class ="path">'.$path.'</td>';
  echo "</tr>";
}
?>

</tbody>
<tfoot>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</tfoot>
</table>

<center><h1>List of agents: m2</h1></center>
<table id="example2" class="display" style="width:100%">
<thead>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</thead>
<tbody>

<?php

$response = CallAPI("GET", "http://".$host.":5000/api/v1/resources/output_php?model=m2");
$response = json_decode($response);

foreach ($response as $value) {
  echo "<tr>";
  $agent_id = $value[0];
  $data = str_replace("[", "", $value[1]);
  $data = str_replace("]", "", $data);
  $data = explode(" ", $data);
  $sugar = $data[0];
  $metabolism = $data[1];
  $vision = $data[2];
  $path = $value[2];
  $processed = $value[3];
  echo '<td class="ids">'.$agent_id.'</td>';
  echo '<td>'.$sugar.'</td>';
  echo '<td>'.$metabolism.'</td>';
  echo '<td class="vision">'.$vision.'</td>';
  echo '<td>'.$processed.'</td>';
  if (in_array(($agent_id), $out)) {
    echo '<td>'."<button value='".$agent_id."' class='btnSubmit buttonSubmit' type='button'>".$agent_id."</button>".'</td>';
  }
  else
    echo '<td><button>'."No File".'</button></td>';

  echo '<td>'.$path.'</td>';
  echo "</tr>";
}

?>

</tbody>
<tfoot>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</tfoot>
</table>

<center><h1>List of agents: m3</h1></center>
<table id="example3" class="display" style="width:100%">
<thead>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</thead>
<tbody>

<?php

$response = CallAPI("GET", "http://".$host.":5000/api/v1/resources/output_php?model=m3");
$response = json_decode($response);

foreach ($response as $value) {
  echo "<tr>";

  $agent_id = $value[0];
  $data = str_replace("[", "", $value[1]);
  $data = str_replace("]", "", $data);
  $data = explode(" ", $data);
  $sugar = $data[0];
  $metabolism = $data[1];
  $vision = $data[2];
  $path = $value[2];
  $processed = $value[3];
  echo '<td class="ids">'.$agent_id.'</td>';
  echo '<td>'.$sugar.'</td>';
  echo '<td>'.$metabolism.'</td>';
  echo '<td class="vision">'.$vision.'</td>';
  echo '<td>'.$processed.'</td>';
  if (in_array(($agent_id), $out)) {
    echo '<td>'."<button value='".$agent_id."' class='btnSubmit buttonSubmit' type='button'>".$agent_id."</button>".'</td>';
  }
  else
    echo '<td><button>'."No File".'</button></td>';

  echo '<td>'.$path.'</td>';
  echo "</tr>";
}

?>

</tbody>
<tfoot>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</tfoot>
</table>

<center><h1>List of agents: router</h1></center>
<table id="example4" class="display" style="width:100%">
<thead>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</thead>
<tbody>

<?php

$response = CallAPI("GET", "http://".$host.":5000/api/v1/resources/output_php?model=router");
$response = json_decode($response);

foreach ($response as $value) {
  echo "<tr>";
  $agent_id = $value[0];
  $data = str_replace("[", "", $value[1]);
  $data = str_replace("]", "", $data);
  $data = explode(" ", $data);
  $sugar = $data[0];
  $metabolism = $data[1];
  $vision = $data[2];
  $path = $value[2];
  $processed = $value[3];
  echo '<td class="ids">'.$agent_id.'</td>';
  echo '<td>'.$sugar.'</td>';
  echo '<td>'.$metabolism.'</td>';
  echo '<td class="vision">'.$vision.'</td>';
  echo '<td>'.$processed.'</td>';
  if (in_array(($agent_id), $out)) {
    echo '<td>'."<button value='".$agent_id."' class='btnSubmit buttonSubmit' type='button'>".$agent_id."</button>".'</td>';
  }
  else
    echo '<td><button>'."No File".'</button></td>';

  echo '<td>'.$path.'</td>';
  echo "</tr>";
}

?>

</tbody>
<tfoot>
<tr>
<th>ID</th>
<th>Sugar</th>
<th>Metabolism</th>
<th>Vision</th>
<th>Processed</th>
<th>File</th>
<th>Traveling Path</th>
</tr>
</tfoot>
</table>

<center><h1>Biggest Path:</h1></center>
<center><h3 id='biggest_path'></h3></center>

<br> <br>
<center><h1>Conteúdo de Arquivo</h1></center>
<pre id="contents" class="normal">Content of file will be load here when you press the button</pre>

  <style>
    tfoot input {
      width: 100%;
      padding: 3px;
      box-sizing: border-box;
    }

    pre {
      white-space: pre-wrap;       /* Since CSS 2.1 */
      white-space: -moz-pre-wrap;  /* Mozilla, since 1999 */
      white-space: -pre-wrap;      /* Opera 4-6 */
      white-space: -o-pre-wrap;    /* Opera 7 */
      word-wrap: break-word;       /* Internet Explorer 5.5+ */
    }
  </style>


  <script type="text/javascript">
    var ids = [];
    var vision = [];
    var final_array = [];

  $(document).ready(function() {
    $(".buttonSubmit").click(function() {
      var fired_button = $(this).html();
      var url = '../jacamo/jacamo_model/src/agt/list/'+fired_button+'.asl';
      var xhr = new XMLHttpRequest();
      xhr.onload = function () {
        document.getElementById('contents').textContent = this.responseText;
      };
      xhr.open('GET', url);
      xhr.send();
    });

    $('#files_table').DataTable();

    $('#example1 tfoot th').each( function () {
      var title = $(this).text();
      $(this).html( '<input type="text" placeholder="Search '+title+'" />' );
    } );

    $('#example2 tfoot th').each( function () {
      var title = $(this).text();
      $(this).html( '<input type="text" placeholder="Search '+title+'" />' );
    } );

    $('#example3 tfoot th').each( function () {
      var title = $(this).text();
      $(this).html( '<input type="text" placeholder="Search '+title+'" />' );
    } );

    $('#example4 tfoot th').each( function () {
      var title = $(this).text();
      $(this).html( '<input type="text" placeholder="Search '+title+'" />' );
    } );

    // DataTable
    var table = $('#example1').DataTable({
      initComplete: function () {
            // Apply the search
            this.api().columns().every( function () {
              var that = this;

              $( 'input', this.footer() ).on( 'keyup change clear', function () {
                if ( that.search() !== this.value ) {
                  that
                  .search( this.value )
                  .draw();
                }
              } );
            } );
          }
        });

    // DataTable
    var table = $('#example2').DataTable({
      initComplete: function () {
            // Apply the search
            this.api().columns().every( function () {
              var that = this;

              $( 'input', this.footer() ).on( 'keyup change clear', function () {
                if ( that.search() !== this.value ) {
                  that
                  .search( this.value )
                  .draw();
                }
              } );
            } );
          }
        });

    // DataTable
    var table = $('#example3').DataTable({
      initComplete: function () {
            // Apply the search
            this.api().columns().every( function () {
              var that = this;

              $( 'input', this.footer() ).on( 'keyup change clear', function () {
                if ( that.search() !== this.value ) {
                  that
                  .search( this.value )
                  .draw();
                }
              } );
            } );
          }
        });

    // DataTable
    var table = $('#example4').DataTable({
      initComplete: function () {
            // Apply the search
            this.api().columns().every( function () {
              var that = this;

              $( 'input', this.footer() ).on( 'keyup change clear', function () {
                if ( that.search() !== this.value ) {
                  that
                  .search( this.value )
                  .draw();
                }
              } );
            } );
          }
        });

  } );

$('#example .ids').each(function() {
    ids.push($(this).html())
  });

  for(var i=0; i<vision.length; i++) {
    final_array.push({x: ids[i].replace(/\D/g, ""), y: vision[i].replace(/\D/g, "")});
  }

  var maxlen=0;
  var tdLongest;
  $('.path').each(function(){
    if($(this).text().length > maxlen)
    {
      maxlen = $(this).text().length;
      tdLongest = $(this);
    }
  });

  $('#biggest_path').text(tdLongest.text());
</script>