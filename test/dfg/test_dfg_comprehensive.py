"""
Comprehensive test suite for DFG (Data Flow Graph) implementation.

This module provides end-to-end validation of DFG generation for both C and Java,
including def-use chains, use-def chains, and inter-procedural parameter aliasing.
"""

from typing import Any, Tuple

import pytest

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.analyses.use_def import UseDefSolver
from tree_climber.dataflow.solver import WorklistSolver


class DFGTestHelper:
    """Helper class for DFG testing and validation."""

    def __init__(self, language: str):
        self.language = language
        self.builder = CFGBuilder(language)
        self.builder.setup_parser()
        self.current_cfg = None  # Store current CFG for assertions

    def build_dfg_from_code(self, code: str) -> Tuple[CFG, Any, Any]:
        """Build CFG and compute DFG analysis from source code."""
        cfg = self.builder.build_cfg(code)
        self.current_cfg = cfg  # Store for assertion methods

        # Run dataflow analysis
        problem = ReachingDefinitionsProblem()
        solver = WorklistSolver()
        dataflow_result = solver.solve(cfg, problem)

        # Compute def-use and use-def chains
        def_use_solver = DefUseSolver()
        def_use_result = def_use_solver.solve(cfg, dataflow_result)

        use_def_solver = UseDefSolver()
        use_def_result = use_def_solver.solve(cfg, dataflow_result)

        return cfg, def_use_result, use_def_result

    def assert_def_use_chain(
        self,
        def_use_result: Any,
        variable: str,
        def_source: str,
        use_source: str,
        msg: str = "",
    ):
        """Assert that a specific def-use chain exists."""
        chains = def_use_result.chains.get(variable, [])

        # Find the definition chain that matches def_source
        matching_chain = None
        for chain in chains:
            # Get actual source text from CFG nodes
            def_node = (
                self.current_cfg.nodes.get(chain.definition)
                if self.current_cfg
                else None
            )
            def_text = def_node.source_text.strip() if def_node else ""

            # Check if definition source matches
            if def_source in def_text:
                # Check if any use matches use_source
                for use_id in chain.uses:
                    use_node = (
                        self.current_cfg.nodes.get(use_id) if self.current_cfg else None
                    )
                    use_text = use_node.source_text.strip() if use_node else ""
                    if use_source in use_text:
                        matching_chain = chain
                        break
            if matching_chain:
                break

        assert matching_chain is not None, (
            f"Expected def-use chain for variable '{variable}' from '{def_source}' to '{use_source}' not found. {msg}\n"
            f"Available chains: {self._format_def_use_chains(chains)}"
        )

    def assert_use_def_chain(
        self,
        use_def_result: Any,
        variable: str,
        use_source: str,
        def_source: str,
        msg: str = "",
    ):
        """Assert that a specific use-def chain exists."""
        chains = use_def_result.chains.get(variable, [])

        # Find the use chain that matches use_source
        matching_chain = None
        for chain in chains:
            # Get actual source text from CFG nodes
            use_node = (
                self.current_cfg.nodes.get(chain.use) if self.current_cfg else None
            )
            use_text = use_node.source_text.strip() if use_node else ""

            if use_source in use_text:
                # Check if any definition matches def_source
                for def_id in chain.definitions:
                    def_node = (
                        self.current_cfg.nodes.get(def_id) if self.current_cfg else None
                    )
                    def_text = def_node.source_text.strip() if def_node else ""
                    if def_source in def_text:
                        matching_chain = chain
                        break
            if matching_chain:
                break

        assert matching_chain is not None, (
            f"Expected use-def chain for variable '{variable}' from use '{use_source}' to def '{def_source}' not found. {msg}\n"
            f"Available chains: {self._format_use_def_chains(chains)}"
        )

    def assert_parameter_alias(
        self,
        def_use_result: Any,
        parameter: str,
        argument_def: str,
        parameter_use: str,
        msg: str = "",
    ):
        """Assert that parameter aliasing works correctly."""
        chains = def_use_result.chains.get(parameter, [])

        # Look for a chain where the parameter use is reached by the argument definition
        found_alias = False
        for chain in chains:
            # Get actual source text from CFG nodes
            def_node = (
                self.current_cfg.nodes.get(chain.definition)
                if self.current_cfg
                else None
            )
            def_text = def_node.source_text.strip() if def_node else ""

            # Check if this chain represents the argument -> parameter alias
            def_matches = argument_def in def_text

            if def_matches:
                # Check if any use matches parameter_use
                for use_id in chain.uses:
                    use_node = (
                        self.current_cfg.nodes.get(use_id) if self.current_cfg else None
                    )
                    use_text = use_node.source_text.strip() if use_node else ""
                    if parameter_use in use_text:
                        found_alias = True
                        break
            if found_alias:
                break

        assert found_alias, (
            f"Expected parameter alias for '{parameter}' from argument def '{argument_def}' to use '{parameter_use}' not found. {msg}\n"
            f"Available chains: {self._format_def_use_chains(chains)}"
        )

    def assert_variable_count(
        self, def_use_result: Any, expected_count: int, msg: str = ""
    ):
        """Assert that the expected number of variables are tracked."""
        actual_count = len(def_use_result.chains)
        assert actual_count == expected_count, (
            f"Expected {expected_count} variables, got {actual_count}. {msg}\n"
            f"Variables: {list(def_use_result.chains.keys())}"
        )

    def debug_dfg_chains(
        self,
        cfg: CFG,
        def_use_result: Any,
        use_def_result: Any,
        title: str = "DFG Debug",
    ):
        """Print detailed DFG chain information for debugging."""
        print(f"\n{title}")
        print("=" * 60)

        print(f"Function: {cfg.function_name}")
        print(f"Variables tracked: {list(def_use_result.chains.keys())}")

        print("\nDef-Use Chains:")
        for var_name, chains in def_use_result.chains.items():
            print(f"  Variable '{var_name}':")
            for chain in chains:
                def_node = cfg.nodes.get(chain.definition)
                def_text = (
                    def_node.source_text.strip()
                    if def_node
                    else f"node_{chain.definition}"
                )
                print(f"    Definition at node {chain.definition}: '{def_text}'")
                for use_id in chain.uses:
                    use_node = cfg.nodes.get(use_id)
                    use_text = (
                        use_node.source_text.strip() if use_node else f"node_{use_id}"
                    )
                    print(f"      -> Used at node {use_id}: '{use_text}'")

        print("\nUse-Def Chains:")
        for var_name, chains in use_def_result.chains.items():
            print(f"  Variable '{var_name}':")
            for chain in chains:
                use_node = cfg.nodes.get(chain.use)
                use_text = (
                    use_node.source_text.strip() if use_node else f"node_{chain.use}"
                )
                print(f"    Use at node {chain.use}: '{use_text}'")
                for def_id in chain.definitions:
                    def_node = cfg.nodes.get(def_id)
                    def_text = (
                        def_node.source_text.strip() if def_node else f"node_{def_id}"
                    )
                    print(f"      <- Defined at node {def_id}: '{def_text}'")

    def _format_def_use_chains(self, chains: list) -> str:
        """Format def-use chains for debugging output."""
        if not chains:
            return "[]"

        formatted_chains = []
        for chain in chains:
            def_node = (
                self.current_cfg.nodes.get(chain.definition)
                if self.current_cfg
                else None
            )
            def_text = (
                def_node.source_text.strip() if def_node else f"node_{chain.definition}"
            )

            use_texts = []
            for use_id in chain.uses:
                use_node = (
                    self.current_cfg.nodes.get(use_id) if self.current_cfg else None
                )
                use_text = (
                    use_node.source_text.strip() if use_node else f"node_{use_id}"
                )
                use_texts.append(f"'{use_text}'")

            formatted_chains.append(
                f"def '{def_text}' -> uses [{', '.join(use_texts)}]"
            )

        return "[" + ", ".join(formatted_chains) + "]"

    def _format_use_def_chains(self, chains: list) -> str:
        """Format use-def chains for debugging output."""
        if not chains:
            return "[]"

        formatted_chains = []
        for chain in chains:
            use_node = (
                self.current_cfg.nodes.get(chain.use) if self.current_cfg else None
            )
            use_text = use_node.source_text.strip() if use_node else f"node_{chain.use}"

            def_texts = []
            for def_id in chain.definitions:
                def_node = (
                    self.current_cfg.nodes.get(def_id) if self.current_cfg else None
                )
                def_text = (
                    def_node.source_text.strip() if def_node else f"node_{def_id}"
                )
                def_texts.append(f"'{def_text}'")

            formatted_chains.append(
                f"use '{use_text}' <- defs [{', '.join(def_texts)}]"
            )

        return "[" + ", ".join(formatted_chains) + "]"


# Test Classes


class TestBasicDefUse:
    """Test basic def-use chain functionality."""

    @pytest.fixture(params=["c", "java"])
    def helper(self, request):
        return DFGTestHelper(request.param)

    def test_simple_assignment(self, helper):
        """Test basic variable assignment and use."""
        if helper.language == "c":
            code = """
            int main() {
                int x = 5;
                int y = x + 1;
                return y;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int main() {
                    int x = 5;
                    int y = x + 1;
                    return y;
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # Should track x and y
        helper.assert_variable_count(
            def_use_result, 2, "Should track x and y variables"
        )

        # x should be defined and used in y assignment
        helper.assert_def_use_chain(
            def_use_result,
            "x",
            "x = 5",
            "y = x + 1",
            "x definition should reach its use",
        )

        # y should be defined and used in return
        helper.assert_def_use_chain(
            def_use_result,
            "y",
            "y = x + 1",
            "return y",
            "y definition should reach return",
        )

    def test_variable_redefinition(self, helper):
        """Test variable redefinition and proper def-use chains."""
        if helper.language == "c":
            code = """
            int main() {
                int x = 5;
                int y = x;
                x = 10;
                int z = x;
                return z;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int main() {
                    int x = 5;
                    int y = x;
                    x = 10;
                    int z = x;
                    return z;
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # x should have two definitions with different uses
        x_chains = def_use_result.chains.get("x", [])
        assert len(x_chains) == 2, (
            f"Expected 2 def-use chains for x, got {len(x_chains)}"
        )

        # First definition (x = 5) should reach y assignment
        helper.assert_def_use_chain(
            def_use_result, "x", "x = 5", "y = x", "First x definition should reach y"
        )

        # Second definition (x = 10) should reach z assignment
        helper.assert_def_use_chain(
            def_use_result, "x", "x = 10", "z = x", "Second x definition should reach z"
        )

    def test_bare_identifier_on_right_hand_side_is_a_use(self, helper):
        """A lone identifier as an initializer or assignment value is a use."""
        if helper.language == "c":
            code = """
            int main() {
                int x = 5;
                int y = x;
                int z;
                z = x;
                return y + z;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int main() {
                    int x = 5;
                    int y = x;
                    int z;
                    z = x;
                    return y + z;
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        helper.assert_def_use_chain(def_use_result, "x", "x = 5", "y = x")
        helper.assert_def_use_chain(def_use_result, "x", "x = 5", "z = x")
        helper.assert_use_def_chain(use_def_result, "x", "z = x", "x = 5")

    def test_conditional_definitions(self, helper):
        """Test def-use chains with conditional statements."""
        if helper.language == "c":
            code = """
            int main() {
                int x;
                if (1) {
                    x = 5;
                } else {
                    x = 10;
                }
                int y = x;
                return y;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int main() {
                    int x;
                    if (true) {
                        x = 5;
                    } else {
                        x = 10;
                    }
                    int y = x;
                    return y;
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # x should have definitions from both branches reaching the use
        use_def_chains = use_def_result.chains.get("x", [])

        # Find the chain for the use in "int y = x"
        y_assignment_chain = None
        for chain in use_def_chains:
            if "y = x" in cfg.nodes[chain.use].source_text:
                y_assignment_chain = chain
                break

        assert y_assignment_chain is not None, (
            "Should find use-def chain for x in y assignment"
        )

        # Should have definitions from both conditional branches
        definition_texts = sorted(
            cfg.nodes[def_id].source_text.strip()
            for def_id in y_assignment_chain.definitions
        )
        assert definition_texts == ["x = 10;", "x = 5;"]
        assert len(y_assignment_chain.definitions) >= 1, (
            "x use should have at least one reaching definition"
        )


@pytest.mark.xfail(
    strict=True,
    reason="Interprocedural parameter aliasing is deferred to vNext (see TODO.md)",
)
class TestInterproceduralAnalysis:
    """Test inter-procedural dataflow analysis."""

    @pytest.fixture(params=["c", "java"])
    def helper(self, request):
        return DFGTestHelper(request.param)

    def test_simple_parameter_alias(self, helper):
        """Test basic parameter aliasing between caller and callee."""
        if helper.language == "c":
            code = """
            void helper(int a) {
                int b = a + 1;
            }
            
            int main() {
                int x = 5;
                helper(x);
                return 0;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static void helper(int a) {
                    int b = a + 1;
                }
                
                public static void main(String[] args) {
                    int x = 5;
                    helper(x);
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # Parameter 'a' should be aliased to argument 'x'
        helper.assert_parameter_alias(
            def_use_result,
            "a",
            "x = 5",
            "b = a + 1",
            "Parameter 'a' should alias to argument 'x'",
        )

    def test_multiple_parameters(self, helper):
        """Test parameter aliasing with multiple parameters."""
        if helper.language == "c":
            code = """
            int add(int a, int b) {
                return a + b;
            }
            
            int main() {
                int x = 5;
                int y = 3;
                int result = add(x, y);
                return result;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int add(int a, int b) {
                    return a + b;
                }
                
                public static void main(String[] args) {
                    int x = 5;
                    int y = 3;
                    int result = add(x, y);
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # Both parameters should be aliased to their respective arguments
        helper.assert_parameter_alias(
            def_use_result,
            "a",
            "x = 5",
            "return a + b",
            "Parameter 'a' should alias to argument 'x'",
        )
        helper.assert_parameter_alias(
            def_use_result,
            "b",
            "y = 3",
            "return a + b",
            "Parameter 'b' should alias to argument 'y'",
        )

    def test_nested_function_calls(self, helper):
        """Test parameter aliasing with nested function calls."""
        if helper.language == "c":
            code = """
            int leaf(int x) {
                return x * 2;
            }
            
            int intermediate(int y) {
                return leaf(y) + 1;
            }
            
            int main() {
                int a = 5;
                int result = intermediate(a);
                return result;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int leaf(int x) {
                    return x * 2;
                }
                
                public static int intermediate(int y) {
                    return leaf(y) + 1;
                }
                
                public static void main(String[] args) {
                    int a = 5;
                    int result = intermediate(a);
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # Check the aliasing chain: a -> y -> x
        helper.assert_parameter_alias(
            def_use_result,
            "y",
            "a = 5",
            "leaf(y)",
            "Parameter 'y' should alias to argument 'a'",
        )
        helper.assert_parameter_alias(
            def_use_result,
            "x",
            "a = 5",
            "return x * 2",
            "Parameter 'x' should alias through the call chain",
        )


class TestIncrementOperators:
    """Test increment and decrement operator def-use behavior.

    An increment both uses and defines its variable. The value it defines can
    only reach the same increment on a later loop iteration, so a self-reference
    appears in loops but not in straight-line code.
    """

    @pytest.fixture(params=["c", "java"])
    def helper(self, request):
        return DFGTestHelper(request.param)

    @staticmethod
    def _wrap(helper, c_body, java_body):
        if helper.language == "c":
            return f"int main() {{\n{c_body}\n}}"
        return f"public class Test {{\npublic static int main() {{\n{java_body}\n}}\n}}"

    @staticmethod
    def _chains_by_text(cfg, def_use_result, variable):
        """Map each definition's source text to the source texts of its uses."""
        return {
            cfg.nodes[chain.definition].source_text.strip(): [
                cfg.nodes[use].source_text.strip() for use in chain.uses
            ]
            for chain in def_use_result.chains.get(variable, [])
        }

    @staticmethod
    def _node_id(cfg, text):
        matches = [
            node_id
            for node_id, node in cfg.nodes.items()
            if node.source_text.strip() == text
        ]
        assert len(matches) == 1, f"Expected exactly one node '{text}', got {matches}"
        return matches[0]

    def test_postfix_increment_straight_line(self, helper):
        """a++ uses the prior definition and defines the one that reaches the return."""
        code = self._wrap(
            helper,
            "int a = 5; a++; return a;",
            "int a = 5; a++; return a;",
        )

        cfg, def_use_result, _ = helper.build_dfg_from_code(code)

        assert self._chains_by_text(cfg, def_use_result, "a") == {
            "int a = 5;": ["a++;"],
            "a++;": ["return a;"],
        }

    def test_prefix_increment_straight_line(self, helper):
        """++a uses the prior definition and defines the one that reaches the return."""
        code = self._wrap(
            helper,
            "int a = 5; ++a; return a;",
            "int a = 5; ++a; return a;",
        )

        cfg, def_use_result, _ = helper.build_dfg_from_code(code)

        assert self._chains_by_text(cfg, def_use_result, "a") == {
            "int a = 5;": ["++a;"],
            "++a;": ["return a;"],
        }

    def test_increment_in_expression(self, helper):
        """An increment inside an expression still uses and defines its variable."""
        code = self._wrap(
            helper,
            "int a = 5; int b = a++ + 1; return b;",
            "int a = 5; int b = a++ + 1; return b;",
        )

        cfg, def_use_result, _ = helper.build_dfg_from_code(code)

        increment_node = self._node_id(cfg, "int b = a++ + 1;")
        metadata = cfg.nodes[increment_node].metadata
        assert "a" in metadata.variable_definitions
        assert "a" in metadata.variable_uses

        chains = self._chains_by_text(cfg, def_use_result, "a")
        assert chains == {"int a = 5;": ["int b = a++ + 1;"]}, (
            "The new value of a is never read, so the increment has no outgoing chain"
        )

    def test_multiple_increments_chain_in_order(self, helper):
        """Successive increments and decrements each feed only the next one."""
        code = self._wrap(
            helper,
            "int a = 5; a++; ++a; a--; return a;",
            "int a = 5; a++; ++a; a--; return a;",
        )

        cfg, def_use_result, _ = helper.build_dfg_from_code(code)

        assert self._chains_by_text(cfg, def_use_result, "a") == {
            "int a = 5;": ["a++;"],
            "a++;": ["++a;"],
            "++a;": ["a--;"],
            "a--;": ["return a;"],
        }

    def test_increment_in_while_loop_references_itself(self, helper):
        """In a loop, the value a++ defines reaches the next iteration's a++."""
        code = self._wrap(
            helper,
            "int a = 0; while (a < 10) { a++; } return a;",
            "int a = 0; while (a < 10) { a++; } return a;",
        )

        cfg, def_use_result, _ = helper.build_dfg_from_code(code)

        increment = self._node_id(cfg, "a++;")
        increment_chain = next(
            chain
            for chain in def_use_result.chains["a"]
            if chain.definition == increment
        )
        assert increment in increment_chain.uses, "a++ should reach itself via the loop"

        use_texts = {cfg.nodes[use].source_text.strip() for use in increment_chain.uses}
        assert use_texts == {"(a < 10)", "a++;", "return a;"}

    def test_increment_in_for_loop_references_itself(self, helper):
        """In a for loop, i++ reaches itself and the loop condition."""
        code = self._wrap(
            helper,
            "for (int i = 0; i < 3; i++) { } return 0;",
            "for (int i = 0; i < 3; i++) { } return 0;",
        )

        cfg, def_use_result, _ = helper.build_dfg_from_code(code)

        chains = self._chains_by_text(cfg, def_use_result, "i")
        assert set(chains["i++"]) == {"i < 3", "i++"}
        assert set(chains["int i = 0;"]) == {"i < 3", "i++"}


class TestComplexDataflow:
    """Test complex dataflow scenarios."""

    @pytest.fixture(params=["c", "java"])
    def helper(self, request):
        return DFGTestHelper(request.param)

    def test_loop_with_function_calls(self, helper):
        """Test dataflow analysis with loops and function calls."""
        if helper.language == "c":
            code = """
            int process(int val) {
                return val * 2;
            }
            
            int main() {
                int sum = 0;
                for (int i = 0; i < 3; i++) {
                    sum = sum + process(i);
                }
                return sum;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int process(int val) {
                    return val * 2;
                }
                
                public static void main(String[] args) {
                    int sum = 0;
                    for (int i = 0; i < 3; i++) {
                        sum = sum + process(i);
                    }
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # sum should have multiple definitions due to loop
        sum_chains = def_use_result.chains.get("sum", [])
        assert len(sum_chains) >= 2, (
            f"Expected at least 2 def-use chains for sum, got {len(sum_chains)}"
        )

        # Parameter 'val' should be aliased to loop variable 'i'
        val_chains = def_use_result.chains.get("val", [])
        assert len(val_chains) >= 1, (
            f"Expected at least 1 def-use chain for val, got {len(val_chains)}"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="Interprocedural parameter aliasing is deferred to vNext (see TODO.md)",
    )
    def test_parameter_modification(self, helper):
        """Test when parameters are modified within functions."""
        if helper.language == "c":
            code = """
            int modify(int p) {
                p = p + 10;
                return p * 2;
            }
            
            int main() {
                int x = 5;
                int result = modify(x);
                return result;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static int modify(int p) {
                    p = p + 10;
                    return p * 2;
                }
                
                public static void main(String[] args) {
                    int x = 5;
                    int result = modify(x);
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # Parameter 'p' should have multiple definitions
        p_chains = def_use_result.chains.get("p", [])
        assert len(p_chains) >= 2, (
            f"Expected at least 2 def-use chains for p, got {len(p_chains)}"
        )

        # Original parameter should alias to argument
        helper.assert_parameter_alias(
            def_use_result,
            "p",
            "x = 5",
            "p = p + 10",
            "Original parameter should alias to argument",
        )

    def test_parameter_redefinition_kills_alias(self, helper):
        """Test that parameter redefinition should kill the original alias."""
        if helper.language == "c":
            code = """
            void helper(int a) {
                a = 10;
                int b = a + 1;
            }
            
            int main() {
                int x = 5;
                helper(x);
                return 0;
            }
            """
        else:  # java
            code = """
            public class Test {
                public static void helper(int a) {
                    a = 10;
                    int b = a + 1;
                }
                
                public static void main(String[] args) {
                    int x = 5;
                    helper(x);
                }
            }
            """

        cfg, def_use_result, use_def_result = helper.build_dfg_from_code(code)

        # Debug the current chains
        helper.debug_dfg_chains(
            cfg, def_use_result, use_def_result, "Parameter redefinition test"
        )

        # Find the use of 'a' in "int b = a + 1"
        a_use_chains = use_def_result.chains.get("a", [])
        b_assignment_chain = None
        for chain in a_use_chains:
            use_node = cfg.nodes.get(chain.use)
            if use_node and "b = a + 1" in use_node.source_text:
                b_assignment_chain = chain
                break

        assert b_assignment_chain is not None, (
            "Should find use-def chain for 'a' in 'b = a + 1'"
        )

        # The use of 'a' in "int b = a + 1" should ONLY reach the definition "a = 10"
        # It should NOT reach the original argument definition "x = 5"
        reaching_defs = []
        for def_id in b_assignment_chain.definitions:
            def_node = cfg.nodes.get(def_id)
            if def_node:
                reaching_defs.append(def_node.source_text.strip())

        # Should only have "a = 10" as reaching definition, not "x = 5"
        assert any("a = 10" in def_text for def_text in reaching_defs), (
            "Should have 'a = 10' as reaching definition"
        )
        assert not any("x = 5" in def_text for def_text in reaching_defs), (
            f"Should NOT have 'x = 5' as reaching definition. Found: {reaching_defs}"
        )


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v"])
