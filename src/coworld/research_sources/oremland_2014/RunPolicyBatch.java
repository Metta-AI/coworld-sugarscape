import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;
import org.nlogo.headless.HeadlessWorkspace;

/** Evaluate complete 50-step policies without per-step observation overhead. */
public class RunPolicyBatch {
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        HeadlessWorkspace workspace = HeadlessWorkspace.newInstance();
        BufferedReader input = Files.newBufferedReader(Paths.get(args[1]));
        BufferedWriter output = Files.newBufferedWriter(Paths.get(args[2]),
            java.nio.file.StandardOpenOption.CREATE_NEW);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        JSONParser parser = new JSONParser();
        try {
            workspace.open(Paths.get(args[0]).toAbsolutePath().toString());
            // GUI histogram callbacks cannot represent extinction and are not model dynamics.
            workspace.plotManager().forgetAll();
            String line;
            while ((line = input.readLine()) != null) {
                JSONObject request = (JSONObject) parser.parse(line);
                JSONArray policy = (JSONArray) request.get("policy");
                if (policy.size() != 200) throw new IllegalArgumentException("Expected 200 rates");
                StringBuilder schedule = new StringBuilder("[");
                for (Object entry : policy) {
                    double rate = ((Number) entry).doubleValue();
                    if (!(rate == 0 || rate == 0.25 || rate == 0.5 || rate == 0.75))
                        throw new IllegalArgumentException("Invalid rate");
                    schedule.append(rate).append(" ");
                }
                schedule.append("]");
                Number seedValue = (Number) request.get("seed");
                Number phaseValue = (Number) request.get("phase");
                int seed = seedValue.intValue();
                int phase = phaseValue.intValue();
                if (seedValue.doubleValue() != seed || phaseValue.doubleValue() != phase)
                    throw new IllegalArgumentException("Seed and phase must be exact 32-bit integers");
                long started = System.nanoTime();
                workspace.command("setup-experiment " + seed
                    + " " + schedule + " " + phase
                    + " " + ((Boolean) request.get("clipped")));
                workspace.command("repeat 50 [go]");
                byte[] hash = digest.digest(workspace.report("survivor-state").toString().getBytes(StandardCharsets.UTF_8));
                StringBuilder hex = new StringBuilder();
                for (byte value : hash) hex.append(String.format("%02x", value & 255));
                JSONObject result = new JSONObject();
                result.put("id", request.get("id"));
                result.put("seed", request.get("seed"));
                result.put("phase", request.get("phase"));
                result.put("clipped", request.get("clipped"));
                result.put("steps", workspace.report("ticks"));
                result.put("population", workspace.report("count turtles"));
                result.put("total_tax", workspace.report("total-tax"));
                result.put("debt_refund", workspace.report("debt-refund"));
                result.put("state_sha256", hex.toString());
                result.put("elapsed_seconds", (System.nanoTime() - started) / 1e9);
                output.write(result.toJSONString());
                output.write("\n");
                output.flush();
            }
        } finally {
            input.close();
            output.close();
            ((org.nlogo.job.JobManager) workspace.jobManager).die();
        }
    }
}
