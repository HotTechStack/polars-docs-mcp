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


@mcp.tool(description="Search and retrieve Polars API signatures and descriptions.")
async def search_polars_docs(
        api_refs: list[str] | None = None,
        query: str | None = None,
        max_results: int = 1000,
        temperature: float = 0.2,
) -> str:
    """
    Search and retrieve Polars API signatures and descriptions.

    This tool inspects all public classes in the `polars` package (DataFrame,
    LazyFrame, Series, Expr, GroupBy, etc.) and returns structured JSON
    entries with `{name, signature, description}` for the requested APIs.

    Behavior:
      - If `api_refs` is provided:
        • Entries without a dot (e.g. `"DataFrame"`) return *all* methods of that class.
        • Entries with a dot (e.g. `"Expr.add"`) return exactly that one method.
        • Returns every match (ignores `max_results` when `api_refs` is used).
      - If `api_refs` is None and `query` is provided:
        • Performs case‑insensitive substring search on both names and descriptions.
        • If no direct matches, falls back to fuzzy name matching.
        • Returns up to `max_results` items.
      - `temperature` is reserved for future ranking/LLM‑driven sorting (currently unused).
      - Use 'io' api for database related references
        - Use 'functions' api for functions related references
        - Use 'convert' api for convert related references

    Args:
        api_refs (list[str] | None):
            Optional list of Polars API identifiers.
            - `"Component"` returns all `Component.*` methods.
            - `"Component.method"` returns that exact signature.
        query (str | None):
            Optional substring to search for in API names or descriptions.
        max_results (int):
            Maximum number of entries to return for substring/fuzzy searches.
        temperature (float):
            Controls randomness in ranking (not used in this implementation).

    Returns:
        str: A JSON‑encoded list of objects:
            [
              {
                "name": "DataFrame.filter",
                "signature": "DataFrame.filter(self, predicate: IntoExpr) -> DataFrame",
                "description": "Filter rows by predicate expression."
              },
              ...
            ]

    Example:
        # Get all DataFrame methods
        search_polars_docs(api_refs=["DataFrame"])

        # Get just the 'add' method on Expr
        search_polars_docs(api_refs=["Expr.add"])

        # Search for any API relating to 'join'
        search_polars_docs(query="join", max_results=10)
    """

    # 1) Build the full API index
    components = discover_polars_components()
    all_apis: list[dict] = []
    for comp_name, comp in components.items():
        for attr_name, member in inspect.getmembers(comp, predicate=inspect.isroutine):
            if attr_name.startswith("_"):
                continue
            try:
                sig = str(inspect.signature(getattr(comp, attr_name)))
            except (ValueError, TypeError):
                sig = "(...)"
            doc = inspect.getdoc(getattr(comp, attr_name)) or ""
            short_doc = doc.strip().split("\n")[0]
            all_apis.append({
                "name": f"{comp_name}.{attr_name}",
                "signature": f"{comp_name}.{attr_name}{sig}",
                "description": short_doc
            })

    picked: list[dict]
    if api_refs:
        picked = []
        # for each ref, collect matching APIs
        for ref in api_refs:
            if "." in ref:
                # exact Component.method match
                picked += [api for api in all_apis if api["name"] == ref]
            else:
                # component-level: match Component.*
                prefix = f"{ref}."
                picked += [api for api in all_apis if api["name"].startswith(prefix)]
        # dedupe and preserve order
        seen = set()
        deduped = []
        for api in picked:
            key = api["name"]
            if key not in seen:
                seen.add(key)
                deduped.append(api)
        picked = deduped

    else:
        # substring + fuzzy fallback as before
        q = (query or "").lower()
        picked = [api for api in all_apis
                  if q in api["name"].lower() or q in api["description"].lower()]
        if not picked and query:
            names = [api["name"].split(".", 1)[1] for api in all_apis]
            close = difflib.get_close_matches(query, names, n=max_results, cutoff=0.1)
            picked = [api for api in all_apis
                      if api["name"].split(".", 1)[1] in close]

    # limit results
    return json.dumps(picked[:max_results], indent=2)


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
        for attr_name, member in inspect.getmembers(comp, predicate=inspect.isroutine):
            if attr_name.startswith("_"):
                continue
            try:
                sig = str(inspect.signature(getattr(comp, attr_name)))
            except (ValueError, TypeError):
                sig = "(...)"
            full_sig = f"{comp_name}.{attr_name}{sig}"
            all_apis.append({"name": f"{comp_name}.{attr_name}", "signature": full_sig})

    # Find matches
    matches = [api for api in all_apis if api_ref == api["name"] or api_ref == api["signature"]]
    valid = len(matches) > 0
    return json.dumps({"valid": valid, "matches": matches}, indent=2)


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