/*
 * SQL injection with the built-in Java rules: servlet parameters and headers,
 * `System.getenv` and `readLine` into the SQL text of `executeQuery`,
 * `executeUpdate`, `execute` and `prepareStatement`, directly, through
 * concatenation, a helper's parameter and a returned value, loops and
 * branches; and prepared statements, constants and reassignment, which are not
 * findings.
 */
import java.io.BufferedReader;
import java.io.IOException;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import javax.servlet.http.HttpServletRequest;

public class Search {
    private Connection connection;

    void direct(HttpServletRequest request) throws SQLException {
        String term = request.getParameter("q");
        Statement statement = connection.createStatement();
        // ruleid: java-sql-injection
        statement.executeQuery("SELECT * FROM t WHERE name = '" + term + "'");
        // ruleid: java-sql-injection
        statement.executeUpdate("DELETE FROM t WHERE id = " + request.getHeader("X-Id"));
        // ok: java-sql-injection
        statement.executeQuery("SELECT * FROM t");
    }

    void prepared(HttpServletRequest request) throws SQLException {
        String term = request.getParameter("q");
        // ok: java-sql-injection
        PreparedStatement safe = connection.prepareStatement("SELECT * FROM t WHERE name = ?");
        safe.setString(1, term);
        // ok: java-sql-injection
        safe.executeQuery();
        // ruleid: java-sql-injection
        connection.prepareStatement("SELECT * FROM t WHERE name = '" + term + "'");
    }

    void helper(HttpServletRequest request) throws SQLException {
        find(request.getParameter("q"));
    }

    void find(String term) throws SQLException {
        String sql = "SELECT * FROM t WHERE name = '" + term + "'";
        // ruleid: java-sql-injection
        connection.createStatement().execute(sql);
    }

    String table() {
        return System.getenv("TABLE");
    }

    void returned() throws SQLException {
        // ruleid: java-sql-injection
        connection.createStatement().executeQuery("SELECT * FROM " + table());
    }

    void loop(BufferedReader reader) throws IOException, SQLException {
        String line;
        while ((line = reader.readLine()) != null) {
            // ruleid: java-sql-injection
            connection.createStatement().execute(line);
        }
    }

    void branch(HttpServletRequest request, boolean admin) throws SQLException {
        String sql = "SELECT 1";
        if (admin) {
            sql = request.getParameter("sql");
        }
        // ruleid: java-sql-injection
        connection.createStatement().execute(sql);
    }

    void reassigned(HttpServletRequest request) throws SQLException {
        String sql = request.getParameter("sql");
        sql = "SELECT 1";
        // ok: java-sql-injection
        connection.createStatement().execute(sql);
    }
}
