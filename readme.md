# Top-N Interface Traffic Visibility-SONiC Feature


## Project Overview

This project implements a **Top-N Interface Traffic Visibility** feature for **SONiC** (Software for Open Networking in the Cloud), Microsoft's open-source network operating system used in large-scale data center switches.

The goal is simple: **given hundreds of network interfaces on a switch, instantly identify which ones are carrying the most traffic.**

This is critical for:
- **Network operators** diagnosing congestion or unexpected traffic spikes
- **Capacity planners** identifying links approaching saturation
- **Automation pipelines** that need programmatic access to traffic rankings

---
## CounterDB Overview

The data source for this project is COUNTERS_DB, a Redis database embedded in SONiC that stores real-time telemetry for every hardware object on the switch. It is exported as a flat JSON file for use in this prototype. It is a Mock Database that is present in Sonic Utilities for testing.

### Top-Level JSON Structure

Every entry in the exported JSON follows this exact pattern:

```
"<TABLE_NAME>:oid:<hex_object_id>": {
  "expireat": <unix_timestamp>,
  "ttl": -0.001,
  "type": "hash",
  "value": { ... stat key-value pairs ... }
}
```


| Field      | What It Means                                                                |
| ---------- | ---------------------------------------------------------------------------- |
| TABLE_NAME | Category of the stat: COUNTERS, QUEUE_STAT_WATERMARKS, USER_WATERMARKS       |
| oid:0x...  | Object ID, a hex identifier for a specific hardware object (port, queue, PG) |
| expireat   | Unix timestamp of when this snapshot was captured                            |
| ttl        | `-0.001` → Entry never expires (persisted in Redis)                          |
| type       | Redis data type → `hash`                                                     |
| value      | Key-value pairs of SAI stat names to raw integer values                      |

### Table Namespaces

The JSON file contains three distinct table prefixes, each tracking a different hardware layer:

| Table Prefix          | Hardware Layer       | What It Tracks                                   |
| --------------------- | -------------------- | ------------------------------------------------ |
| COUNTERS              | Port level           | Per-interface packet and byte stats (RX/TX)      |
| QUEUE_STAT_WATERMARKS | Queue level          | Peak memory usage per egress queue               |
| USER_WATERMARKS       | Priority Group level | Buffer headroom usage for PFC per priority class |

### Counter Fields Inside value

For COUNTERS (port-level stats), the value object holds SAI standard counter names:

| SAI Counter Name                    | Meaning                              |
| ----------------------------------- | ------------------------------------ |
| SAI_PORT_STAT_IF_IN_OCTETS          | Total bytes received                 |
| SAI_PORT_STAT_IF_OUT_OCTETS         | Total bytes sent                     |
| SAI_PORT_STAT_IF_IN_UCAST_PKTS      | Unicast packets received             |
| SAI_PORT_STAT_IF_OUT_UCAST_PKTS     | Unicast packets sent                 |
| SAI_PORT_STAT_IF_IN_DISCARDS        | Incoming packets dropped             |
| SAI_PORT_STAT_PFC_0_RX_PKTS → PFC_7 | PFC packets per priority class (0–7) |

For USER_WATERMARKS, the value object holds priority group buffer stats:

| SAI Counter Name                                          | Meaning                    |
| --------------------------------------------------------- | -------------------------- |
| SAI_INGRESS_PRIORITY_GROUP_STAT_SHARED_WATERMARK_BYTES    | Peak shared buffer usage   |
| SAI_INGRESS_PRIORITY_GROUP_STAT_XOFF_ROOM_WATERMARK_BYTES | Peak headroom buffer usage |

Important note: all counter values in COUNTERS_DB are monotonically increasing cumulative totals, not rates. Computing actual traffic rates requires taking two snapshots separated by a time interval and computing the delta between them.

## The Prototype
The prototype is a standalone Python CLI tool that reads a single static JSON snapshot of COUNTERS_DB and prints the top N interfaces by total bytes (RX plus TX). It is intentionally minimal, focused entirely on proving out the core data parsing and ranking logic before integrating into SONiC CLI.
### Project Structure
```
project/
  main.py              Entry point, argument parsing, table rendering
  core/
    processor.py       JSON parsing, counter extraction, heap-based ranking
  utils/
    math_engine.py     Counter delta helper and byte formatter
  data/
    counter_db.json    Static JSON snapshot of COUNTERS_DB
```
###  Usage
```
# Show top 5 interfaces
python main.py 5

# Show top 10 interfaces
python main.py 10
```
The Output I get from Usage of Mock CounterDB: 

<img width="785" height="262" alt="Screenshot 2026-04-08 231240" src="https://github.com/user-attachments/assets/82b80b66-a995-4a66-b552-756442559a6c" />

## Core Logic
This is the most important section. The two key algorithmic decisions in the prototype are the heap-based top-N selection and the counter extraction strategy. Everything else is plumbing.
### Why a Min-Heap
The naive approach to finding the top N items from a list of k items is to sort everything and take the first N. That costs O(k log k) time and O(k) space, where k is the total number of interfaces on the switch. In large deployments k can be in the hundreds.

The prototype instead uses a min-heap of fixed size N. The algorithm works as follows:

1. Push every interface into the heap as a tuple of (total_bytes, interface_info)
2. After each push, if the heap size exceeds N, pop the smallest element
3. At the end of the loop, the heap contains exactly the top N interfaces
4. Sort the heap in descending order for display

This reduces time complexity to O(k log N) and space complexity to O(N). When N is 5 and k is 500, that is a significant difference. Python's heapq module implements a min-heap natively, so the smallest total_bytes value is always at the root and gets evicted first whenever the heap overflows N.

### Counter Key Filtering

The JSON snapshot contains entries from all three table namespaces (COUNTERS, QUEUE_STAT_WATERMARKS, USER_WATERMARKS). The processor filters to only port-level entries by checking the key prefix:
```if key.startswith("COUNTERS:oid"):```
This is the correct filter. Only COUNTERS prefix entries contain SAI_PORT_STAT_IF_IN_OCTETS and SAI_PORT_STAT_IF_OUT_OCTETS. Watermark entries use entirely different stat names and would cause KeyError or silently return zero if not filtered.

### RX and TX Extraction
Inside each matching entry, the processor pulls two specific fields from the value hash:
```
rx_bytes = int(vals.get('SAI_PORT_STAT_IF_IN_OCTETS', 0))
tx_bytes = int(vals.get('SAI_PORT_STAT_IF_OUT_OCTETS', 0))
total_bytes = rx_bytes + tx_bytes

```
Using .get() with a default of 0 is important because some interfaces (especially admin-down ones) may be missing certain counter fields entirely. Casting to int is required because Redis stores all values as strings, and that carries through to the JSON export.
### The ns_diff Function
math_engine.py contains a function called ns_diff that computes the delta between two counter snapshots:
```

def ns_diff(new_val, old_val):
    diff = int(new_val) - int(old_val)
    return max(0, diff)

```
This function exists in the codebase but is not yet wired into the prototype. It clamps negative values to zero to handle counter resets, which can happen when a line card reboots or when the counter overflows its 64-bit register. This function is the bridge between a static snapshot reader and a live rate calculator, and it is exactly what needs to be wired in for the actual solution.
## Byte Formatting
format_brate() in math_engine.py converts raw byte counts into human-readable strings using simple threshold checks:
```
if rate > 10**9:  return GB/s
elif rate > 10**6:  return MB/s
elif rate > 10**3:  return KB/s
else:  return B/s

```
The function is named format_brate (byte rate) but currently receives cumulative byte totals from the snapshot, not per-second rates. In the final solution, after delta calculations are wired in, this function will be receiving genuine per-second values and the output labels will be accurate.
## What the Actual Solution Will Look Like
The prototype validates the parsing and ranking logic. The actual solution integrates into SONiC CLI, adds delta-based rate computation, and exposes additional output options. Here is how it differs from the prototype and what needs to be built.
### Delta-Based Rate Calculation
The most critical gap in the prototype is that it reads cumulative byte totals from a single snapshot. Real traffic rates require two snapshots separated by a known time interval. The actual solution will:

1. Take snapshot 1 of COUNTERS_DB, record timestamp t1
2. Sleep for a configurable interval (default 1 second)
3. Take snapshot 2 of COUNTERS_DB, record timestamp t2
4. For each interface, compute delta_rx = ns_diff(snap2_rx, snap1_rx) and delta_tx = ns_diff(snap2_tx, snap1_tx)
5. Divide by (t2 - t1) to get bytes per second
6. Run the heap ranking on per-second values instead of cumulative totals

ns_diff() already handles counter resets and edge cases. The interval between snapshots becomes a CLI parameter.

### SONiC CLI Integration
The actual solution will be integrated into sonic-utilities as a new CLI command. The target interface will look like:
```
$ show interfaces top-traffic
$ show interfaces top-traffic --count 10
$ show interfaces top-traffic --interval 5
$ show interfaces top-traffic --json
```
This means replacing the main.py standalone script with a Click command group entry that follows the sonic-utilities conventions for argument parsing and output formatting.

### Live COUNTERS_DB Access
The prototype reads from a static JSON file. The actual solution will read directly from the Redis instance running inside the SONiC container using the sonic-py-swsssdk or the newer sonic-db-cli interface. The read logic in processor.py stays almost identical, but instead of opening a file it will query Redis hash fields directly using HGETALL on each COUNTERS:oid key.
### JSON Output Mode
For automation and integration with external monitoring systems like Grafana, the solution will support a --json flag that outputs results as structured JSON instead of the tabulate table. The heap result is already a Python data structure, so this is a straightforward serialization step.
### Feature Summary
| Feature                   | Prototype                              | Actual Solution                                      |
|---------------------------|----------------------------------------|------------------------------------------------------|
| Data source               | Static JSON file                       | Live Redis query via swsssdk                         |
| Rate calculation          | Cumulative totals (incorrect)          | Delta between two timed snapshots                    |
| CLI                       | `python main.py <N>`                   | `show interfaces top-traffic` with Click             |
| Configurable interval     | Not supported                          | CLI flag (default: 1 second)                         |
| JSON output               | Not supported                          | CLI flag `--json`                                    |
| Counter reset handling    | `ns_diff` exists but unused            | Fully integrated into delta calculation              |
| SONiC integration         | Standalone script                      | Merged into `sonic-utilities` package                |


The prototype is a correct and clean proof of concept. All the core algorithmic work (heap ranking, SAI key filtering, byte formatting, counter diff safety) is already done. The actual solution is primarily an integration and wiring exercise on top of this foundation.
