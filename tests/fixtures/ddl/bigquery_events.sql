CREATE TABLE `analytics.user_events` (
    event_id      STRING      NOT NULL,
    user_id       STRING      NOT NULL,
    event_type    STRING      NOT NULL,
    event_ts      TIMESTAMP   NOT NULL,
    properties    JSON,
    session_id    STRING,
    platform      STRING
);
