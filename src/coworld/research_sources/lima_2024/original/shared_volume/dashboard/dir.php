var files = <?php $out = array();
foreach (glob('../jacamo/src/src/agt/list/*.asl') as $filename) {
    $p = pathinfo($filename);
    $out[] = $p['filename'];
}
echo json_encode($out); ?>;