import matplotlib.pyplot as plt

def parse_trace_cycles_between_markers(filename, marker="0x32951073"):
    """
    Parses a trace file and extracts a list of commit cycles between two occurrences of a marker instruction.
    """
    cycles = []
    collecting = False
    marker_count = 0

    with open(filename, 'r') as file:
        for line in file:
            if marker in line and not(marker in prevline):
                marker_count += 1
                if marker_count == 1:
                    collecting = True  # Start collecting from the first marker
                elif marker_count == 2:
                    # Still collect this line, then stop after this
                    try:
                        cycle_str = line.split('@')[1].split()[0]
                        cycle = int(cycle_str)
                        cycles.append(cycle)
                    except (IndexError, ValueError):
                        pass
                    break  # Exit after second marker
            prevline = line
            if collecting and '@' in line:
                try:
                    cycle_str = line.split('@')[1].split()[0]
                    cycle = int(cycle_str)
                    cycles.append(cycle)
                except (IndexError, ValueError):
                    continue

    return cycles

def compute_deltas(cycles):
    return [cycles[i+1] - cycles[i] for i in range(len(cycles) - 1)]

def compare_deltas(deltas1, deltas2):
    return sum(1 for d1, d2 in zip(deltas1, deltas2) if d1 == d2)

"""
def plot_deltas(deltas1, deltas2, filename1, filename2):
    plt.figure(figsize=(12, 6))

    # Histogram for trace 1
    plt.subplot(1, 2, 1)
    plt.hist(deltas1, bins=range(min(deltas1 + deltas2), max(deltas1 + deltas2) + 2), color='blue', alpha=0.7)
    plt.title(f'Delta Distribution for {filename1}')
    plt.xlabel('Delta (cycles)')
    plt.ylabel('Frequency')

    # Histogram for trace 2
    plt.subplot(1, 2, 2)
    plt.hist(deltas2, bins=range(min(deltas1 + deltas2), max(deltas1 + deltas2) + 2), color='green', alpha=0.7)
    plt.title(f'Delta Distribution for {filename2}')
    plt.xlabel('Delta (cycles)')
    plt.ylabel('Frequency')

    plt.tight_layout()
    plt.show()
"""

def plot_overlayed_deltas(deltas1, deltas2, label1, label2):
    all_deltas = deltas1 + deltas2
    bins = range(min(all_deltas), max(all_deltas) + 2)  # +2 to include upper edge

    plt.figure(figsize=(10, 6))
    plt.hist(deltas1, bins=bins, alpha=0.5, label=label1, color='blue', edgecolor='black')
    plt.hist(deltas2, bins=bins, alpha=0.5, label=label2, color='green', edgecolor='black')

    plt.title('Overlayed Delta Distribution Between Markers')
    plt.xlabel('Delta (cycles)')
    plt.ylabel('Frequency')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

def main(trace1_path, trace2_path, marker="0x32951073"):
    cycles1 = parse_trace_cycles_between_markers(trace1_path, marker)
    cycles2 = parse_trace_cycles_between_markers(trace2_path, marker)
    print(len(cycles1), len(cycles2))
    print(cycles1[0:10], cycles2[0:10])
    if len(cycles1) < 2 or len(cycles2) < 2:
        print("Not enough instructions found between markers in one or both files.")
        return

    deltas1 = compute_deltas(cycles1)
    deltas2 = compute_deltas(cycles2)
    #for i in range(300000,310000,10):
    #   print(deltas1[i:10+i], deltas2[i:10+i])
    match_count = compare_deltas(deltas1, deltas2)
    print(f"Matching delta count between markers: {match_count}")
    
    plot_overlayed_deltas(deltas1, deltas2, trace1_path, trace2_path)

# Example usage
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python compare_deltas.py <trace1.txt> <trace2.txt>")
    else:
        main(sys.argv[1], sys.argv[2])