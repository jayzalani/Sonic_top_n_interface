# Top-N Interface Traffic Visibility-SONiC Feature

## Table of Contents

1. [Project Overview](#project-overview)
2. [Problem Statement](#problem-statement)
3. [Repository Structure](#repository-structure)
4. [The Prototype-What It Is and Why It Exists](#the-prototype)
5. [Min-Heap Algorithm-Deep Explanation](#min-heap-algorithm)
6. [Prototype Walkthrough-File by File](#prototype-walkthrough)
7. [Prototype Limitations](#prototype-limitations)
8. [The Actual Solution-Architecture](#the-actual-solution)
9. [Full Data Flow](#full-data-flow)
10. [Key Difference: Single Snapshot vs Delta Sampling](#key-difference)
11. [How to Run the Prototype](#how-to-run-the-prototype)
12. [What Comes Next](#what-comes-next)

---

## Project Overview

This project implements a **Top-N Interface Traffic Visibility** feature for **SONiC** (Software for Open Networking in the Cloud), Microsoft's open-source network operating system used in large-scale data center switches.

The goal is simple: **given hundreds of network interfaces on a switch, instantly identify which ones are carrying the most traffic.**

This is critical for:
- **Network operators** diagnosing congestion or unexpected traffic spikes
- **Capacity planners** identifying links approaching saturation
- **Automation pipelines** that need programmatic access to traffic rankings

---

## Problem Statement

SONiC already collects per-interface traffic counters and exposes them via `show interfaces counters`. However, on a switch with 128+ interfaces, an operator must manually scan every row to find the busiest ones. This is:

- **Slow**-reading 128 rows takes time and attention
- **Error-prone**-humans miss rows under pressure
- **Not automation-friendly**-no machine-readable sorted output exists

**What we need:** A single command that answers *"which interfaces are carrying the most traffic right now?"* in under 5 seconds.

---

## Repository Structure

### Prototype Layout

```mermaid
graph TD
    ROOT["project-root/"]
    CORE["core/"]
    UTILS["utils/"]
    DATA["data/"]
    MAIN["main.py\nEntry point-wires all layers together"]
    README["README.md"]

    INIT1["__init__.py"]
    PROC["processor.py\nMin-heap logic\nReads counter DB\nReturns top-N"]

    INIT2["__init__.py"]
    MATH["math_engine.py\nns_diff()-delta calculation\nformat_brate()-human readable rates"]

    DB["counter_db.json\nMock COUNTERS_DB\nMirrors real Redis structure\nNo switch needed for dev"]

    ROOT --> CORE
    ROOT --> UTILS
    ROOT --> DATA
    ROOT --> MAIN
    ROOT --> README

    CORE --> INIT1
    CORE --> PROC

    UTILS --> INIT2
    UTILS --> MATH

    DATA --> DB
```

### How Prototype Maps to Real SONiC Repository

```mermaid
graph LR
    subgraph PROTOTYPE["Prototype"]
        MP["main.py"]
        PP["core/processor.py"]
        ME["utils/math_engine.py"]
    end

    subgraph SONIC["sonic-utilities (Production)"]
        SI["show/interfaces.py\nClick CLI command"]
        PS["utilities_common/portstat.py\nPortstat class"]
        NS["utilities_common/netstat.py\nns_diff, format_brate"]
        TS["tests/top_n_interface_test.py"]
    end

    MP -->|"moves to"| SI
    PP -->|"moves to"| PS
    ME -->|"already exists as"| NS
    MP -->|"tests move to"| TS
```

---

## The Prototype

### What It Is

The prototype is a **standalone Python script** that simulates the core logic of the final feature **without requiring a real SONiC switch or Redis database**. It reads from a local JSON file that mirrors the exact structure of SONiC's `COUNTERS_DB`.

### Why Build a Prototype First

Before integrating into a complex codebase like `sonic-utilities`, a prototype lets you:

1. **Validate the algorithm**-confirm the min-heap produces correct rankings
2. **Understand the data shape**-explore what COUNTERS_DB actually contains
3. **Test formatting**-see what output looks like before wiring up CLI
4. **Iterate fast**-no SONiC environment needed, runs anywhere with Python

### Prototype Internal Architecture

```mermaid
graph TD
    USER(["User: python main.py 5"])

    subgraph MAIN_LAYER["main.py-Display Layer"]
        ARGS["Parse CLI args\nn = 5"]
        TABULATE["tabulate()\nRender table to terminal"]
    end

    subgraph CORE_LAYER["core/processor.py-Computation Layer"]
        READ["Open counter_db.json\nParse all keys"]
        FILTER["Filter keys starting\nwith COUNTERS:oid"]
        EXTRACT["Extract rx_bytes\ntx_bytes per interface"]
        HEAP["Min-Heap of size N\nMaintain top-N by total bytes"]
        SORT["Sort heap descending\nReturn ranked list"]
    end

    subgraph MATH_LAYER["utils/math_engine.py-Math Layer"]
        BRATE["format_brate()\nBytes to KB/MB/GB string"]
    end

    subgraph DATA_LAYER["data/counter_db.json-Data Layer"]
        JSON["Mock COUNTERS_DB\nSAI_PORT_STAT_IF_IN_OCTETS\nSAI_PORT_STAT_IF_OUT_OCTETS"]
    end

    USER --> ARGS
    ARGS --> READ
    READ --> JSON
    JSON --> FILTER
    FILTER --> EXTRACT
    EXTRACT --> HEAP
    HEAP --> SORT
    SORT --> TABULATE
    TABULATE --> BRATE
    BRATE --> TABULATE
```

---

## Min-Heap Algorithm

This is the most important algorithmic decision in the entire project. Understanding it deeply will matter when you present or defend the implementation.

### The Naive Approach (Do Not Use)

The obvious solution to "find top N from a list" is:

```python
# Sort all interfaces by traffic
all_interfaces = sorted(all_data, key=lambda x: x['total'], reverse=True)
# Take first N
top_n = all_interfaces[:n]
```

**Why this is wrong for production:**

On a 128-port switch, this sorts all 128 entries every time. SONiC runs on switches with up to **512 interfaces**. You asked for top 5-you do not need to precisely sort the bottom 507. Time complexity: **O(k log k)** where k = total interfaces.

### The Min-Heap Approach (What We Use)

A **min-heap of size N** maintains only the N largest elements seen so far. The ROOT of the heap is always the **smallest** of the current top-N-the first one to get evicted when a better candidate arrives.

### Step-by-Step Heap Walkthrough (top 3 from 6 interfaces)

```mermaid
flowchart TD
    START(["Start: want top 3, heap is empty"])

    S1["Push Ethernet0 total=500\nHeap: [500]"]
    S2["Push Ethernet4 total=1200\nHeap: [500, 1200]"]
    S3["Push Ethernet8 total=300\nHeap: [300, 1200, 500]\nSize = N = 3, Root = 300 smallest"]

    S4_CHECK{"Push Ethernet12 total=800\n800 > root 300?"}
    S4_YES["POP 300, Ethernet8 eliminated\nPUSH 800\nHeap: [500, 1200, 800]"]

    S5_CHECK{"Push Ethernet16 total=100\n100 > root 500?"}
    S5_NO["DO NOTHING\nEthernet16 eliminated immediately\nHeap unchanged: [500, 1200, 800]"]

    S6_CHECK{"Push Ethernet20 total=950\n950 > root 500?"}
    S6_YES["POP 500, Ethernet0 eliminated\nPUSH 950\nHeap: [800, 1200, 950]"]

    FINAL["Final Heap: [800, 1200, 950]\nSort descending: [1200, 950, 800]"]
    RESULT(["Result: Ethernet4, Ethernet20, Ethernet12"])

    START --> S1 --> S2 --> S3
    S3 --> S4_CHECK
    S4_CHECK -->|Yes| S4_YES
    S4_YES --> S5_CHECK
    S5_CHECK -->|No| S5_NO
    S5_NO --> S6_CHECK
    S6_CHECK -->|Yes| S6_YES
    S6_YES --> FINAL --> RESULT
```

### Heap State at Key Steps

```mermaid
graph TD
    subgraph STEP3["After Step 3-Heap Full at N=3"]
        R3["300 ROOT\nEthernet8\nSmallest, evicted next"]
        C3A["1200\nEthernet4"]
        C3B["500\nEthernet0"]
        R3 --> C3A
        R3 --> C3B
    end

    subgraph STEP4["After Step 4-Ethernet8 evicted"]
        R4["500 ROOT\nEthernet0\nNow weakest member"]
        C4A["1200\nEthernet4"]
        C4B["800\nEthernet12"]
        R4 --> C4A
        R4 --> C4B
    end

    subgraph FINAL2["Final-After Step 6"]
        R5["800 ROOT\nEthernet12"]
        C5A["1200\nEthernet4"]
        C5B["950\nEthernet20"]
        R5 --> C5A
        R5 --> C5B
    end

    STEP3 -->|"Ethernet12=800 arrives\n800 > 300, evict 300"| STEP4
    STEP4 -->|"Ethernet20=950 arrives\n950 > 500, evict 500"| FINAL2
```

### Complexity Comparison

| Approach | Time Complexity | Space Complexity | k=512, n=5 |
|---|---|---|---|
| Sort all | O(k log k) | O(k) | 4,608 operations |
| Min-heap | O(k log n) | O(n) | 1,177 operations |

The heap does **75% less work** and holds only N items in memory regardless of total interface count.

### The Code

```python
# core/processor.py

import heapq

min_heap = []

for key, content in data.items():
    if key.startswith("COUNTERS:oid"):

        rx_bytes = int(vals.get('SAI_PORT_STAT_IF_IN_OCTETS', 0))
        tx_bytes = int(vals.get('SAI_PORT_STAT_IF_OUT_OCTETS', 0))
        total_bytes = rx_bytes + tx_bytes

        # Python's heapq is a MIN-heap
        # heapq compares on the first element of the tuple
        entry = (total_bytes, info_dict)
        heapq.heappush(min_heap, entry)

        # If heap exceeds N, pop the SMALLEST (the root)
        # This keeps only the N largest seen so far
        if len(min_heap) > n:
            heapq.heappop(min_heap)

# Sort the remaining N items descending for display
return sorted(min_heap, key=lambda x: x[0], reverse=True)
```

---

## Prototype Walkthrough-File by File

### `data/counter_db.json`-The Mock Database

This file mirrors the exact structure of SONiC's Redis `COUNTERS_DB`. In production, data lives in Redis. In the prototype, it lives in this JSON file.

```json
{
  "COUNTERS_PORT_NAME_MAP": {
    "value": {
      "Ethernet0": "oid:0x1000000000001",
      "Ethernet4": "oid:0x1000000000002"
    }
  },
  "COUNTERS:oid:0x1000000000001": {
    "value": {
      "SAI_PORT_STAT_IF_IN_OCTETS":  "1048576000",
      "SAI_PORT_STAT_IF_OUT_OCTETS": "524288000"
    }
  }
}
```

### Database Key Structure

```mermaid
erDiagram
    COUNTERS_PORT_NAME_MAP {
        string Ethernet0 "oid:0x1000000000001"
        string Ethernet4 "oid:0x1000000000002"
        string Ethernet8 "oid:0x1000000000003"
    }

    COUNTERS_OID {
        string SAI_PORT_STAT_IF_IN_OCTETS "RX bytes since boot"
        string SAI_PORT_STAT_IF_OUT_OCTETS "TX bytes since boot"
        string SAI_PORT_STAT_IF_IN_UCAST_PKTS "RX packets"
        string SAI_PORT_STAT_IF_OUT_UCAST_PKTS "TX packets"
    }

    COUNTERS_PORT_NAME_MAP ||--o{ COUNTERS_OID : "OID links to counter entry"
```

### `utils/math_engine.py`-Pure Math Layer

```python
def ns_diff(new_val, old_val):
    diff = int(new_val) - int(old_val)
    return max(0, diff)   # guard against counter resets
```

The `max(0, diff)` guard handles counter resets-if a counter rolls back to zero after a reboot or clear, we return 0 instead of a massive negative number.

### Counter Reset Guard Logic

```mermaid
flowchart TD
    INPUT(["ns_diff(new_val, old_val)"])
    CALC["diff = int(new_val) - int(old_val)"]
    CHECK{"diff < 0 ?"}
    NORMAL["return diff\nNormal counter increment"]
    RESET["return 0\nCounter was reset\nreboot or show counters -c\nProtects against negative spike"]

    INPUT --> CALC --> CHECK
    CHECK -->|No| NORMAL
    CHECK -->|Yes| RESET
```

---

## Prototype Limitations

| Gap | Prototype | Production Solution |
|---|---|---|
| **Sampling** | Single snapshot, absolute bytes | Two snapshots, delta = actual rate |
| **Interface names** | Shows raw OIDs | Maps OIDs to Ethernet names |
| **Port state** | Not shown | U / D / X column |
| **Database** | JSON file | Live Redis via `swsscommon` |
| **CLI** | `python main.py` | `show interfaces counters top-n` |
| **JSON flag** | Not supported | `--json` flag |
| **Interval config** | Not supported | `--interval` flag |
| **Utilization %** | Not shown | RX_UTIL and TX_UTIL columns |

---

## The Actual Solution

### Full System Architecture

```mermaid
graph TB
    USER(["Operator\nshow interfaces counters top-n\n--count 5 --interval 3 --json"])

    subgraph CLI["CLI Layer-show/interfaces.py"]
        CMD["@interfaces.command top-n\n--count  --interval  --json"]
        DISP_TABLE["tabulate() table display"]
        DISP_JSON["json.dumps() output"]
    end

    subgraph COMPUTE["Computation Layer-utilities_common/portstat.py"]
        PORTSTAT["class Portstat"]
        GET_TOP["get_top_n_interfaces(n, interval)"]
        GET_CNSTAT["get_cnstat()-existing method, reused"]
        SLEEP["time.sleep(interval)"]
        DELTA["Delta per interface\nrx_delta + tx_delta = total"]
        HEAP2["Min-heap → top N"]
        STATE["get_port_state()\nget_port_speed()"]
    end

    subgraph MATH["Math Layer-utilities_common/netstat.py"]
        NSDIFF["ns_diff()-safe delta"]
        FMTBRATE["format_brate()-human readable"]
    end

    subgraph DB["Database Layer-Redis"]
        MAP["COUNTERS_PORT_NAME_MAP\nEthernet0 → oid:0x1"]
        CTRS["COUNTERS:oid:0x1\nSAI_PORT_STAT_IF_IN_OCTETS\nSAI_PORT_STAT_IF_OUT_OCTETS"]
        APPL["APPL_DB PORT_TABLE\noper_status, admin_status, speed"]
    end

    USER --> CMD
    CMD --> GET_TOP
    GET_TOP --> GET_CNSTAT
    GET_CNSTAT --> MAP
    GET_CNSTAT --> CTRS
    GET_TOP --> SLEEP
    SLEEP --> GET_CNSTAT
    GET_TOP --> DELTA
    DELTA --> NSDIFF
    DELTA --> HEAP2
    HEAP2 --> STATE
    STATE --> APPL
    HEAP2 --> CMD
    CMD -->|"--json flag set"| DISP_JSON
    CMD -->|"default table"| DISP_TABLE
    DISP_TABLE --> FMTBRATE
```

---

## Full Data Flow

```mermaid
sequenceDiagram
    actor User
    participant CLI as show/interfaces.py
    participant Portstat as portstat.py
    participant NetStat as netstat.py
    participant Redis as COUNTERS_DB Redis

    User->>CLI: show interfaces counters top-n --count 5 --interval 3

    CLI->>Portstat: get_top_n_interfaces(n=5, interval=3)

    Note over Portstat: Sample 1 at T=0
    Portstat->>Redis: GET COUNTERS_PORT_NAME_MAP
    Redis-->>Portstat: Ethernet0 oid:0x1, Ethernet4 oid:0x2 ...
    Portstat->>Redis: GET COUNTERS:oid for all ports
    Redis-->>Portstat: rx_bytes, tx_bytes per port
    Note over Portstat: Stored as sample_1

    Note over Portstat: time.sleep(3 seconds)

    Note over Portstat: Sample 2 at T=3
    Portstat->>Redis: GET COUNTERS:oid for all ports
    Redis-->>Portstat: rx_bytes, tx_bytes per port now higher
    Note over Portstat: Stored as sample_2

    loop For each interface
        Portstat->>NetStat: ns_diff(sample2.rx_byt, sample1.rx_byt)
        NetStat-->>Portstat: rx_delta
        Portstat->>NetStat: ns_diff(sample2.tx_byt, sample1.tx_byt)
        NetStat-->>Portstat: tx_delta
        Note over Portstat: total = rx_delta + tx_delta, apply min-heap
    end

    Portstat->>Redis: GET PORT_TABLE oper_status per port
    Redis-->>Portstat: Ethernet0 up, Ethernet4 up ...

    Portstat-->>CLI: sorted top-5 list with deltas and state

    loop For each result row
        CLI->>NetStat: format_brate(rx_delta / interval)
        NetStat-->>CLI: 125.40 MB/s
    end

    CLI-->>User: Rendered table or JSON
```

---

## Key Difference: Single Snapshot vs Delta Sampling

```mermaid
flowchart LR
    subgraph PROTOTYPE["Prototype-Single Snapshot"]
        direction TB
        T_NOW["T = now\nRead counters once"]
        SORT_ABS["Sort by absolute bytes\nsince switch booted"]
        PROBLEM["Problem:\nEthernet0 up 30 days = huge cumulative bytes\nEthernet4 up 1 hour running at 10 GB/s\nEthernet0 ranks higher despite being idle now\nAbsolute bytes is NOT current traffic rate"]
        T_NOW --> SORT_ABS --> PROBLEM
    end

    subgraph PRODUCTION["Production-Delta Sampling"]
        direction TB
        T0["T = 0\nRead counters, store as sample_1"]
        SLEEP2["sleep interval seconds"]
        T3["T = interval\nRead counters, store as sample_2"]
        DELTA2["delta = sample_2 minus sample_1\nbytes moved in exactly N seconds"]
        RATE["rate = delta divided by interval\nbytes per second RIGHT NOW\nTrue current throughput"]
        T0 --> SLEEP2 --> T3 --> DELTA2 --> RATE
    end

    PROTOTYPE -->|"upgrade to"| PRODUCTION
```

---

## How to Run the Prototype

### Prerequisites

```bash
pip install tabulate
```

### Running

```bash
# Default: top 5
python main.py

# Top 10
python main.py 10

# All interfaces
python main.py all
```

### Expected Output

```
--- Top 5 Interfaces ---
Rank  Interface               RX_Total     TX_Total     Total_Bytes
----  ----------------------  -----------  -----------  -----------
1     oid:0x1000000000005     125.40 MB/s  80.20 MB/s   205.60 MB/s
2     oid:0x1000000000002     90.10 MB/s   60.50 MB/s   150.60 MB/s
3     oid:0x1000000000008     40.00 MB/s   20.00 MB/s   60.00 MB/s
4     oid:0x1000000000001     1.20 KB/s    500.00 B/s   1.70 KB/s
5     oid:0x1000000000003     100.00 B/s   50.00 B/s    150.00 B/s
```

> **Note:** Interface names show OIDs in the prototype. The production solution resolves these to `Ethernet0`, `Ethernet4` etc. via `COUNTERS_PORT_NAME_MAP`.

---

## What Comes Next

```mermaid
flowchart LR
    S1["Step 1\nDelta Sampling\nportstat.py"]
    S2["Step 2\nOID to Name\nResolution\nportstat.py"]
    S3["Step 3\nClick Command\nshow/interfaces.py"]
    S4["Step 4\nFlags: count\ninterval, json\nshow/interfaces.py"]
    S5["Step 5\nPort State and\nUtilization columns\nportstat.py"]
    S6["Step 6\nUnit Tests\ntop_n_interface_test.py"]
    S7["Step 7\nPR to\nsonic-utilities"]

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
```

| Step | Task | Files Changed |
|---|---|---|
| 1 | Delta sampling-two `get_cnstat()` calls with `time.sleep()` | `utilities_common/portstat.py` |
| 2 | OID → interface name via `COUNTERS_PORT_NAME_MAP` | `utilities_common/portstat.py` |
| 3 | Click command `show interfaces counters top-n` | `show/interfaces.py` |
| 4 | `--count`, `--interval`, `--json` flags | `show/interfaces.py` |
| 5 | Port state and utilization columns | `utilities_common/portstat.py` |
| 6 | Unit tests using existing mock DB JSON | `tests/top_n_interface_test.py` |
| 7 | PR to sonic-utilities following contribution guidelines | All above files |

---

*This document covers both the prototype (proof of concept) and the full production design. The prototype validates the core algorithm. The production implementation integrates it into SONiC's CLI with real database access, delta sampling, and complete output formatting.*
