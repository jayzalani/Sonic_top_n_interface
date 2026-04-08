import sys
from tabulate import tabulate
from core.processor import TrafficProcessor
from utils.math_engine import format_brate

def run_prototype(count):
    proc = TrafficProcessor('data/counter_db.json')
    top_n_data = proc.get_top_n_heap(n=count)
    table_rows = []
    headers = ["Rank", "Interface", "RX_Total", "TX_Total", "Total_Bytes"]
    for i, (total_val, info) in enumerate(top_n_data, 1):
        row = [
            i,
            info['name'],
            format_brate(info['rx']),
            format_brate(info['tx']),
            format_brate(info['total']),
        ]
        table_rows.append(row)
    print(f"\n--- Top {count} Interfaces ---")
    print(tabulate(table_rows, headers=headers, tablefmt="simple"))

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "5"
    n = 1000 if arg.lower() == 'all' else int(arg)
    run_prototype(n)