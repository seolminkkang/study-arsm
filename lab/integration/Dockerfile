FROM gradle:8.14.3-jdk21 AS build
WORKDIR /src
COPY . .
RUN gradle --no-daemon test bootJar
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/build/libs/integration-lab.jar app.jar
ENTRYPOINT ["java","-jar","app.jar"]
