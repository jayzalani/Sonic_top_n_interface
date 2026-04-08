import json
import heapq

class TrafficProcessor:
    def __init__(self, json_db_path):
        self.db_path = json_db_path

    def get_top_n_heap(self, n=5):
        with open(self.db_path, 'r') as f:
            data = json.load(f)

        min_heap = []
        
        for key, content in data.items():
            if key.startswith("COUNTERS:oid"):
                vals = content.get('value', {})
                # Extracting more raw data
                rx_bytes = int(vals.get('SAI_PORT_STAT_IF_IN_OCTETS', 0))
                tx_bytes = int(vals.get('SAI_PORT_STAT_IF_OUT_OCTETS', 0))
                total_bytes = rx_bytes + tx_bytes
                
                iface_name = key.replace("COUNTERS:", "")
                entry = (total_bytes, {
                    "name": iface_name,
                    "rx": rx_bytes,
                    "tx": tx_bytes,
                    "total": total_bytes,
                })

                heapq.heappush(min_heap, entry)
                if len(min_heap) > n:
                    heapq.heappop(min_heap)

        return sorted(min_heap, key=lambda x: x[0], reverse=True)