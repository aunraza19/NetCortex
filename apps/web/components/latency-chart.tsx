"use client";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { Point } from "@/lib/types";
export function LatencyChart({
  data,
  compact = false,
}: {
  data: Point[];
  compact?: boolean;
}) {
  return (
    <div className={`chart-wrap ${compact ? "chart-compact" : ""}`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
        >
          <defs>
            <linearGradient id="forecast" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#16c7bd" stopOpacity={0.2} />
              <stop offset="100%" stopColor="#16c7bd" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid
            stroke="#24333e"
            strokeDasharray="3 5"
            vertical={false}
          />
          <XAxis
            dataKey="time"
            tick={{ fill: "#748591", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval={compact ? 5 : 3}
          />
          <YAxis
            tick={{ fill: "#748591", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            unit=" ms"
          />
          <Tooltip
            contentStyle={{
              background: "#111e28",
              border: "1px solid #2a3a45",
              borderRadius: 8,
              color: "#e5f0f4",
              fontSize: 12,
            }}
            labelStyle={{ color: "#91a2ad" }}
          />
          <Area
            dataKey="p90"
            stroke="none"
            fill="url(#forecast)"
            isAnimationActive={false}
          />
          <Area
            dataKey="p10"
            stroke="none"
            fill="#0c151d"
            isAnimationActive={false}
          />
          <Line
            dataKey="p50"
            name="Expected"
            stroke="#13bcb2"
            strokeDasharray="5 5"
            strokeWidth={1.7}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="actual"
            name="Actual"
            stroke="#f0f6f7"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            activeDot={{ r: 4, fill: "#13bcb2" }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
