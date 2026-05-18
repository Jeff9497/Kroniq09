# Bug: wrong variable name (typo)
def calculate_average(numbers):
    total = sum(numbers)
    return total / leng(numbers)

scores = [85, 90, 78, 92, 88]
print(f"Average: {calculate_average(scores)}")
