<?xml version='1.0'?> <!--*-nxml-*-->
<!--
    SPDX-License-Identifier: Apache-2.0
    Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
-->

<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">

<xsl:import href="http://docbook.sourceforge.net/release/xsl/current/html/docbook.xsl"/>

<xsl:template name="user.header.content">
  <style>
    a.headerlink {
      color: #c60f0f;
      font-size: 0.8em;
      padding: 0 4px 0 4px;
      text-decoration: none;
      visibility: hidden;
    }

    a.headerlink:hover {
      background-color: #c60f0f;
      color: white;
    }

    h1:hover > a.headerlink, h2:hover > a.headerlink, h3:hover > a.headerlink, dt:hover > a.headerlink {
      visibility: visible;
    }
  </style>


  <a>
    <xsl:text xml:space="preserve" white-space="pre"> &#160; </xsl:text>
  </a>

  <span style="float:right">
    <xsl:text>nvme-stas </xsl:text>
    <xsl:value-of select="$nvme-stas.version"/>
  </span>
  <hr/>
</xsl:template>

<xsl:template match="literal">
  <xsl:text>"</xsl:text>
  <xsl:call-template name="inline.monoseq"/>
  <xsl:text>"</xsl:text>
</xsl:template>

<xsl:output method="html" encoding="UTF-8" indent="no"/>

</xsl:stylesheet>

