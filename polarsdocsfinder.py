from fastmcp import FastMCP
import json
from enum import Enum, auto
from typing import Optional, List, Dict, Union, Literal
import polars as pl
import inspect
import difflib
import importlib
import importlib.metadata
import argparse

# Initialize FastMCP
mcp = FastMCP("Polars Docs Finder with FastMCP")


def discover_polars_components():
    """
    Auto‑discover all public Polars components, including:
     - Classes (DataFrame, LazyFrame, Series, Expr, GroupBy, …)
     - Top‑level functions (read_csv, concat, etc.)
     - Sub‑modules (e.g. polars.io → "io")
    """
    comps = {}

    # 1) Pick up all public classes in polars.*
    for name, obj in vars(pl).items():
        if name.startswith("_"):
            continue
        if inspect.isclass(obj) and obj.__module__.startswith("polars"):
            comps[name] = obj

    # 2) Pick up all public top‑level functions in polars
    for name, obj in vars(pl).items():
        if name.startswith("_"):
            continue
        if inspect.isfunction(obj) and obj.__module__.startswith("polars"):
            comps[name] = obj

    # 3) Explicitly include these sub‑modules
    for sub in ["io", "functions", "convert", "datatypes"]:
        try:
            mod = importlib.import_module(f"polars.{sub}")
            comps[sub] = mod
        except ImportError:
            # skip if not present in this version
            pass

    return comps


@mcp.tool(description="Get the currently installed Polars version information")
def get_polars_version() -> str:
    """
    Get the currently installed Polars version information.

    This tool returns detailed version information about the Polars package
    currently installed in the environment, including the version number,
    installation location, and other metadata.

    Returns:
        str: A JSON-encoded object containing version information:
            {
              "version": "0.20.3",
              "package_name": "polars",
              "location": "/path/to/site-packages",
              "metadata": {
                "author": "...",
                "summary": "...",
                "home_page": "...",
                ...
              }
            }

    Example:
        # Get current Polars version
        get_polars_version()
    """
    try:
        # Get version using importlib.metadata (recommended approach)
        version = importlib.metadata.version("polars")

        # Get additional metadata
        try:
            metadata = importlib.metadata.metadata("polars")
            metadata_dict = dict(metadata)
        except Exception:
            metadata_dict = {}

        # Try to get the module location
        try:
            location = pl.__file__ if hasattr(pl, '__file__') else "Unknown"
            if location and location.endswith("__init__.py"):
                location = location.replace("__init__.py", "")
        except Exception:
            location = "Unknown"

        version_info = {
            "version": version,
            "package_name": "polars",
            "location": location,
            "metadata": metadata_dict
        }

        return json.dumps(version_info, indent=2, default=str)

    except importlib.metadata.PackageNotFoundError:
        # Fallback: try to get version from polars module directly
        try:
            version = getattr(pl, '__version__', 'Unknown')
            version_info = {
                "version": version,
                "package_name": "polars",
                "location": getattr(pl, '__file__', 'Unknown'),
                "metadata": {},
                "note": "Version obtained from module attribute (metadata unavailable)"
            }
            return json.dumps(version_info, indent=2, default=str)

        except Exception as e:
            error_info = {
                "error": "Could not determine Polars version",
                "details": str(e),
                "version": "Unknown",
                "package_name": "polars"
            }
            return json.dumps(error_info, indent=2)


@mcp.tool(description="List all available high‑level Polars API components")
def list_polars_components() -> str:
    """
    List all available high‑level Polars API components.

    This tool inspects the `polars` package and returns every public class
    found in its top‑level namespace (e.g. DataFrame, LazyFrame, Series,
    Expr, GroupBy, DateChunked, etc.). It emits a JSON‑encoded list of
    component names. An LLM can call this first to decide which components
    to pass into `search_polars_docs`.

    Returns:
        str: A JSON‑encoded list of component names, e.g.
            [
              "DataFrame",
              "LazyFrame",
              "Series",
              "Expr",
              "GroupBy",
              ...
            ]

    Example:
        # Discover which Polars components are available
        list_polars_components()
    """
    comps = discover_polars_components()  # returns a dict
    names = list(comps.keys())  # cast dict_keys to a list of str
    return json.dumps(names, indent=2)  # JSON‑encode for the LLM


@mcp.tool(
    description="Search Polars API methods and documentation. Finds exact matches first, then falls back to fuzzy search.")
async def search_polars_api(
        components: str = "",
        methods: str = "",
        max_results: int = 1000,
        debug: bool = False,
) -> str:
    """
    Search Polars API methods and get their signatures and documentation.

    This function is designed for LLMs to easily find Polars methods. It tries multiple
    search strategies automatically:
    1. Exact component matches (case-insensitive)
    2. Exact method matches (case-insensitive)
    3. Fuzzy search as fallback

    Args:
        components (str):
            Polars component names to search (case-insensitive).
            Examples: "dataframe", "DataFrame", "series,lazyframe", "expr"

        methods (str):
            Specific method names to find (case-insensitive).
            Examples: "filter", "join,groupby", "select,with_columns"
            Can be used alone or combined with components.

        max_results (int):
            Maximum number of results to return (default: 50)

        debug (bool):
            Show detailed search process information

    Returns:
        str: JSON array of method information with name, signature, and description

    Examples:
        # Get all DataFrame methods
        search_polars_api(components="dataframe")

        # Get specific methods from any component
        search_polars_api(methods="filter,join")

        # Get specific methods from specific components
        search_polars_api(components="dataframe,series", methods="groupby")

        # Fuzzy search will automatically activate if exact matches fail
        search_polars_api(methods="filtter")  # Will find "filter"
    """

    # Parse and normalize inputs
    component_list = []
    if components.strip():
        component_list = [c.strip().lower() for c in components.split(",") if c.strip()]

    method_list = []
    if methods.strip():
        method_list = [m.strip().lower() for m in methods.split(",") if m.strip()]

    # Debug info
    debug_info = {
        "search_strategy": "",
        "inputs": {
            "components_raw": components,
            "methods_raw": methods,
            "components_parsed": component_list,
            "methods_parsed": method_list
        },
        "search_steps": [],
        "results_found": 0
    }

    if debug:
        print(f"=== Search Input Debug ===")
        print(f"Components: {component_list}")
        print(f"Methods: {method_list}")
        print("=" * 30)

    # Build the full API index with case-insensitive mapping
    components_discovered = discover_polars_components()
    all_apis = []
    component_name_mapping = {}  # lowercase -> actual name

    for comp_name, comp in components_discovered.items():
        if comp is None:
            continue

        # Store case-insensitive mapping
        component_name_mapping[comp_name.lower()] = comp_name

        for attr_name in dir(comp):
            if attr_name.startswith("_"):
                continue

            try:
                member = getattr(comp, attr_name)
                if not (callable(member) or isinstance(member, property)):
                    continue

                try:
                    if callable(member) and not isinstance(member, type):
                        sig = str(inspect.signature(member))
                    else:
                        sig = ""
                except (ValueError, TypeError, AttributeError):
                    sig = "(...)"

                doc = inspect.getdoc(member) or ""
                short_doc = doc.strip().split("\n")[0] if doc.strip() else ""

                if not short_doc and not callable(member):
                    continue

                all_apis.append({
                    "name": f"{comp_name}.{attr_name}",
                    "component": comp_name,
                    "method": attr_name,
                    "signature": f"{comp_name}.{attr_name}{sig}",
                    "description": short_doc
                })

            except (AttributeError, TypeError):
                continue

    debug_info["total_apis"] = len(all_apis)

    # Search Strategy 1: Exact component matches (case-insensitive)
    results = []

    if component_list and not method_list:
        debug_info["search_strategy"] = "exact_components"
        debug_info["search_steps"].append("Searching for exact component matches")

        for comp_lower in component_list:
            if comp_lower in component_name_mapping:
                actual_comp_name = component_name_mapping[comp_lower]
                matches = [api for api in all_apis if api["component"] == actual_comp_name]
                results.extend(matches)
                debug_info["search_steps"].append(f"Found {len(matches)} methods for {actual_comp_name}")

    # Search Strategy 2: Exact method matches (case-insensitive)
    elif method_list and not component_list:
        debug_info["search_strategy"] = "exact_methods"
        debug_info["search_steps"].append("Searching for exact method matches")

        for method_lower in method_list:
            matches = [api for api in all_apis if api["method"].lower() == method_lower]
            results.extend(matches)
            debug_info["search_steps"].append(f"Found {len(matches)} matches for method '{method_lower}'")

    # Search Strategy 3: Component + Method combination
    elif component_list and method_list:
        debug_info["search_strategy"] = "component_and_method"
        debug_info["search_steps"].append("Searching for component + method combinations")

        for comp_lower in component_list:
            if comp_lower in component_name_mapping:
                actual_comp_name = component_name_mapping[comp_lower]
                for method_lower in method_list:
                    matches = [api for api in all_apis
                               if api["component"] == actual_comp_name and api["method"].lower() == method_lower]
                    results.extend(matches)
                    debug_info["search_steps"].append(
                        f"Found {len(matches)} matches for {actual_comp_name}.{method_lower}")

    # Remove duplicates while preserving order
    seen = set()
    unique_results = []
    for api in results:
        key = api["name"]
        if key not in seen:
            seen.add(key)
            unique_results.append(api)
    results = unique_results

    # Search Strategy 4: Fuzzy fallback if no exact matches
    if not results and (component_list or method_list):
        debug_info["search_strategy"] += "_with_fuzzy_fallback"
        debug_info["search_steps"].append("No exact matches found, trying fuzzy search")

        fuzzy_candidates = []

        # Fuzzy search on components
        if component_list:
            all_component_names = [name.lower() for name in component_name_mapping.keys()]
            for comp_lower in component_list:
                close_comps = difflib.get_close_matches(comp_lower, all_component_names, n=3, cutoff=0.6)
                for close_comp in close_comps:
                    actual_comp_name = component_name_mapping[close_comp]
                    comp_matches = [api for api in all_apis if api["component"] == actual_comp_name]
                    fuzzy_candidates.extend(comp_matches)
                    debug_info["search_steps"].append(
                        f"Fuzzy: '{comp_lower}' → '{actual_comp_name}' ({len(comp_matches)} methods)")

        # Fuzzy search on methods
        if method_list:
            all_method_names = list(set(api["method"].lower() for api in all_apis))
            for method_lower in method_list:
                close_methods = difflib.get_close_matches(method_lower, all_method_names, n=5, cutoff=0.6)
                for close_method in close_methods:
                    method_matches = [api for api in all_apis if api["method"].lower() == close_method]
                    fuzzy_candidates.extend(method_matches)
                    debug_info["search_steps"].append(
                        f"Fuzzy: '{method_lower}' → '{close_method}' ({len(method_matches)} matches)")

        # Remove duplicates from fuzzy results
        seen = set()
        for api in fuzzy_candidates:
            key = api["name"]
            if key not in seen:
                seen.add(key)
                results.append(api)

    # Limit results
    final_results = results[:max_results]
    debug_info["results_found"] = len(final_results)

    # Debug output
    if debug:
        print(f"=== Search Strategy Debug ===")
        print(f"Strategy used: {debug_info['search_strategy']}")
        for step in debug_info["search_steps"]:
            print(f"  {step}")
        print(f"Final results: {len(final_results)} items")
        print("=" * 30)

    # Clean up results for output (remove internal fields)
    clean_results = []
    for api in final_results:
        clean_results.append({
            "name": api["name"],
            "signature": api["signature"],
            "description": api["description"]
        })

    # Prepare response
    response = {
        "results": clean_results,
        "total_found": len(final_results),
        "search_strategy": debug_info["search_strategy"]
    }

    if debug:
        response["debug"] = debug_info

    return json.dumps(response, indent=2)


@mcp.tool(description="Verify if a given Polars API name or signature is valid.")
def verify_polars_api(api_ref: str) -> str:
    """
    Verify that the provided Polars API reference or full signature exists.

    Args:
        api_ref (str): An API name (e.g. "DataFrame.filter") or full signature
                       (e.g. "DataFrame.filter(self, predicate: IntoExpr) -> DataFrame").

    Returns:
        str: JSON with {
            "valid": bool,
            "matches": [
               {"name": str, "signature": str},
               ...
            ]
        }
    """
    # Rebuild index of APIs
    components = discover_polars_components()
    all_apis = []

    for comp_name, comp in components.items():
        if comp is None:
            continue

        for attr_name in dir(comp):
            if attr_name.startswith("_"):
                continue
            try:
                member = getattr(comp, attr_name)
                if callable(member):
                    try:
                        sig = str(inspect.signature(member))
                    except (ValueError, TypeError):
                        sig = "(...)"
                    full_sig = f"{comp_name}.{attr_name}{sig}"
                    all_apis.append({"name": f"{comp_name}.{attr_name}", "signature": full_sig})
            except (AttributeError, TypeError):
                continue

    # Find matches
    matches = [api for api in all_apis if api_ref == api["name"] or api_ref == api["signature"]]
    valid = len(matches) > 0
    return json.dumps({"valid": valid, "matches": matches}, indent=2)


@mcp.tool(description="Debug tool to show what components are discovered and their types")
def debug_polars_components() -> str:
    """
    Debug tool to show what components are discovered and their types.
    This helps diagnose issues with component discovery.
    """
    components = discover_polars_components()
    debug_info = []

    for name, comp in components.items():
        comp_info = {
            "name": name,
            "type": type(comp).__name__,
            "module": getattr(comp, '__module__', 'Unknown'),
            "is_class": inspect.isclass(comp),
            "is_function": inspect.isfunction(comp),
            "is_module": inspect.ismodule(comp),
            "methods_count": 0
        }

        # Count methods for classes
        if inspect.isclass(comp) or inspect.ismodule(comp):
            try:
                methods = [attr for attr in dir(comp)
                           if not attr.startswith("_") and callable(getattr(comp, attr, None))]
                comp_info["methods_count"] = len(methods)
                comp_info["sample_methods"] = methods[:5]  # First 5 methods as sample
            except Exception as e:
                comp_info["error"] = str(e)

        debug_info.append(comp_info)

    return json.dumps(debug_info, indent=2, default=str)


@mcp.tool(description="List all modern data stacks that can be used with Polars.")
def list_all_modern_data_stacks():
    """
    List all modern data stacks that can be used with Polars.
    """
    # This is a placeholder function. You can implement it to return a list of
    # modern data stacks that are compatible with Polars.
    return ["DuckDB", "Polars", "Daft", "Hudi", "Iceberg", "Delta Lake", "Apache Arrow", "Apache Parquet", "Xorq"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Polars MCP Server with FastMCP")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="Transport method (default: stdio)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address for HTTP/SSE transports (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8111,
        help="Port number for HTTP/SSE transports (default: 8111)"
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="URL path for streamable-http transport (default: /mcp)"
    )

    args = parser.parse_args()

    print(f"Starting Polars MCP Server with transport: {args.transport}")

    if args.transport == "stdio":
        # STDIO (Default): Best for local tools and command-line scripts
        print("Using STDIO transport - connect via command line or local tools")
        mcp.run(transport="stdio")

    elif args.transport == "streamable-http":
        # Streamable HTTP: Recommended for web deployments
        print(f"Using Streamable HTTP transport on {args.host}:{args.port}{args.path}")
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            path=args.path
        )

    elif args.transport == "sse":
        # SSE: For compatibility with existing SSE clients
        print(f"Using SSE transport on {args.host}:{args.port}")
        mcp.run(
            transport="sse",
            host=args.host,
            port=args.port
        )