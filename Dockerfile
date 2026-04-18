FROM maven:3.9.6-amazoncorretto-17 AS build

WORKDIR /app
ARG APP_MODULE=discord-mcp-app

COPY pom.xml ./
COPY primo-core/pom.xml primo-core/pom.xml
COPY primo-bot-app/pom.xml primo-bot-app/pom.xml
COPY discord-mcp-app/pom.xml discord-mcp-app/pom.xml
COPY . .

RUN mvn -pl ${APP_MODULE} -am clean package -DskipTests

FROM amazoncorretto:17-alpine

ARG APP_MODULE=discord-mcp-app
WORKDIR /app

COPY --from=build /app/${APP_MODULE}/target/${APP_MODULE}-1.0.0.jar app.jar

ENV DISCORD_TOKEN=""
ENV DISCORD_GUILD_ID=""

ENTRYPOINT ["java", "-jar", "app.jar"]
