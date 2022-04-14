<?xml version='1.0'?> <!--*-nxml-*-->
<!--
    SPDX-License-Identifier: Apache-2.0
    Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
-->

<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:exsl="http://exslt.org/common"
                extension-element-prefixes="exsl"
                version="1.0">

<xsl:import href="http://docbook.sourceforge.net/release/xsl/current/manpages/docbook.xsl"/>

<xsl:template name="TH.title.line">
    <xsl:param name="title"/>
    <xsl:param name="section"/>

    <xsl:call-template name="mark.subheading"/>
    <xsl:text>.TH "</xsl:text>

    <xsl:call-template name="string.upper">
      <xsl:with-param name="string">
        <xsl:value-of select="normalize-space($title)"/>
      </xsl:with-param>
    </xsl:call-template>

    <xsl:text>" "</xsl:text>
    <xsl:value-of select="normalize-space($section)"/>

    <xsl:text>" "" "nvme-stas </xsl:text>
    <xsl:value-of select="$nvme-stas.version"/>

    <xsl:text>" "</xsl:text>

    <xsl:text>"&#10;</xsl:text>
    <xsl:call-template name="mark.subheading"/>

</xsl:template>

</xsl:stylesheet>

