/**
 * AlertBar — Global worst-case alert pill shown in the header.
 */

import React from 'react';

const ALERT_LABELS = {
  GREEN: '● SAFE',
  AMBER: '⚠ CAUTION',
  RED:   '◉ DANGER',
};

export default function AlertBar({ alert }) {
  return (
    <div className={`alert-pill ${alert}`} id="global-alert-pill">
      {ALERT_LABELS[alert] || '● SAFE'}
    </div>
  );
}
