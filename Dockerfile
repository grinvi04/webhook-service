# ---- Builder Stage ----
# In this case, we don't have complex build steps, so the builder stage
# is less critical, but it's a good practice for future extensions.
# We'll use it to validate that all dependencies can be installed.
FROM python:3.11-slim as builder

WORKDIR /usr/src/app

COPY requirements.txt requirements-dev.txt ./

# Install all dependencies to ensure they are compatible
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-dev.txt


# ---- Final/Production Stage ----
# This stage creates the final, lean production image.
FROM python:3.11-slim

# Create a non-root user and group
# Using --system creates a user with no password and no home directory in /home
RUN addgroup --system app && adduser --system --ingroup app app

# Set the working directory in the app user's home directory
WORKDIR /home/app

# Copy only the production requirements file
COPY requirements.txt .

# Install production dependencies
# Using a virtual environment is not strictly necessary here as the container
# itself provides isolation.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY ./app ./app
COPY alembic.ini .
COPY alembic ./alembic

# Change ownership of the files to the non-root user
# This is important for security
RUN chown -R app:app .

# Switch to the non-root user
USER app

# Expose the port
EXPOSE 80

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]