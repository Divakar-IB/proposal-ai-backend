from authentication.hash import hash_password, verify_password

password = "Admin@123"

hashed = hash_password(password)

print(f"Original Password : {password}")
print(f"Hashed Password   : {hashed}")

print(verify_password("Admin@123", hashed))
print(verify_password("WrongPassword", hashed))