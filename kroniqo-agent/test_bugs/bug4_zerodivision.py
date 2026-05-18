# Bug: no zero division guard
def get_percentage(part, whole):
    return (part / whole) * 100

results = [
    get_percentage(45, 100),
    get_percentage(30, 60),
    get_percentage(10, 0),   # this will crash
]

for r in results:
    print(f"{r:.1f}%")
