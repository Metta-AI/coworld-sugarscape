import java.nio.file.Files;
import java.nio.file.Path;
import org.nlogo.headless.HeadlessWorkspace;

/** Record a complete native trajectory with the paper's population and combat settings. */
public class Replay {
    public static void main(String[] args) throws Exception {
        if (args.length != 5) {
            throw new IllegalArgumentException("Usage: Replay model group-A group-B steps new-output.csv");
        }
        int steps = Integer.parseInt(args[3]);
        if (steps < 1 || steps > 20000) {
            throw new IllegalArgumentException("Steps must be between 1 and 20000");
        }
        for (int i = 1; i <= 2; i++) {
            if (!java.util.List.of("Rule M", "EC", "Q-Learning", "SARSA").contains(args[i])) {
                throw new IllegalArgumentException("Unknown action rule: " + args[i]);
            }
        }
        Path output = Files.createFile(Path.of(args[4]).toAbsolutePath());
        String[] reporters = {"count group-A", "count group-B", "mean [sugar] of group-A",
            "mean [sugar] of group-B", "mean [vision] of group-A", "mean [vision] of group-B",
            "mean [metabolism] of group-A", "mean [metabolism] of group-B",
            "combat-agent-a-die", "combat-agent-b-die", "starve-agent-a-die", "starve-agent-b-die",
            "mean [age] of group-A", "mean [age] of group-B", "max [age] of group-A", "max [age] of group-B"};
        HeadlessWorkspace workspace = HeadlessWorkspace.newInstance();
        try {
            workspace.open(args[0], true);
            workspace.command("set initial-population 400 set corner-start true set combat true "
                + "set replace-dead true set sugar-growback-rate 1 set visualization \"no-visualization\" "
                + "set group-A-action \"" + args[1] + "\" set group-B-action \"" + args[2] + "\" setup");
            // Agentset reporters randomize traversal. Observation must not advance the model RNG.
            String record = "with-local-randomness [file-print (word ticks";
            for (String reporter : reporters) {
                record += " \",\" (" + reporter + ")";
            }
            record += ")]";
            String escaped = output.toString().replace("\\", "\\\\").replace("\"", "\\\"");
            workspace.command("file-open \"" + escaped + "\" file-print \"tick," + String.join(",", reporters)
                + "\" " + record + " repeat " + steps + " [go " + record + "] file-close");
            var lines = Files.readAllLines(output);
            if (lines.size() != steps + 2) {
                throw new IllegalStateException("Incomplete native trajectory");
            }
            for (int tick = 0; tick <= steps; tick++) {
                String[] fields = lines.get(tick + 1).split(",", -1);
                if (fields.length != 17 || Double.parseDouble(fields[0]) != tick) {
                    throw new IllegalStateException("Invalid observation at tick " + tick);
                }
                for (String field : fields) {
                    if (!Double.isFinite(Double.parseDouble(field))) {
                        throw new IllegalStateException("Nonfinite observation at tick " + tick);
                    }
                }
            }
            System.out.println("Validated " + (steps + 1) + " native observations");
        } finally {
            workspace.dispose();
        }
    }
}
