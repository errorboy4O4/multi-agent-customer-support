-- Runs once, when the Docker volume is first created. The test suite only ever
-- touches databases whose name ends in _test (M2 plan, Review Focus 4).
CREATE DATABASE support_test;
