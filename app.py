#!/usr/bin/env python3
"""CDK app entry point for TrendRadar infrastructure."""
import os
from aws_cdk import App
from infrastructure.cdk_stack import TrendRadarStack

app = App()
TrendRadarStack(app, "TrendRadarStack")
app.synth()
