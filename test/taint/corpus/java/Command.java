/*
 * Command injection with the built-in Java rules (`*.exec`), and the
 * documented Java approximations: writes into fields and array elements
 * define nothing (#32), a call to a mutating method (`append`, `add`, `put`...)
 * taints its receiver, and unknown calls pass taint through.
 */
import java.io.IOException;
import javax.servlet.http.HttpServletRequest;

public class Command {
    private String pending;

    void direct(HttpServletRequest request) throws IOException {
        // ruleid: java-command-injection
        Runtime.getRuntime().exec(request.getParameter("cmd"));
        String host = request.getParameter("host");
        // ruleid: java-command-injection
        Runtime.getRuntime().exec("ping -c 1 " + host.trim());
        // ok: java-command-injection
        Runtime.getRuntime().exec("uptime");
    }

    void field(HttpServletRequest request) throws IOException {
        this.pending = request.getParameter("cmd");
        // todoruleid: java-command-injection -- Java writes into fields define nothing in the CFG (#32)
        Runtime.getRuntime().exec(this.pending);
    }

    void array(HttpServletRequest request) throws IOException {
        String[] argv = new String[2];
        argv[0] = request.getParameter("cmd");
        // todoruleid: java-command-injection -- Java writes into array elements define nothing in the CFG (#32)
        Runtime.getRuntime().exec(argv);
    }

    void builder(HttpServletRequest request) throws IOException {
        StringBuilder command = new StringBuilder("ping ");
        command.append(request.getParameter("host"));
        // ruleid: java-command-injection
        Runtime.getRuntime().exec(command.toString());
    }

    void list(HttpServletRequest request) throws IOException {
        java.util.List<String> argv = new java.util.ArrayList<>();
        argv.add("ping");
        argv.add(request.getParameter("host"));
        // ruleid: java-command-injection
        Runtime.getRuntime().exec(argv.toArray(new String[0]));
    }

    void cleanBuilder(HttpServletRequest request) throws IOException {
        StringBuilder command = new StringBuilder("uptime");
        command.append(" -p");
        // ok: java-command-injection
        Runtime.getRuntime().exec(command.toString());
    }

    void unknown(HttpServletRequest request) throws IOException {
        String level = request.getParameter("level");
        int parsed = Integer.parseInt(level);
        // todook: java-command-injection -- unknown calls pass taint through, even parseInt, whose result is a safe number
        Runtime.getRuntime().exec("nice -n " + parsed + " make");
    }
}
